#!/usr/local/bin/python

import datetime
import os
import random
import re
import signal
import string
import sys
import time

import digitalocean
import requests


class HobbyTester:
    def __init__(
        self,
        token=None,
        name=None,
        region="sfo3",
        image="ubuntu-22-04-x64",
        size="s-4vcpu-8gb",
        release_tag="latest-release",
        branch=None,
        hostname=None,
        domain=None,
        droplet=None,
        record=None,
    ):
        if not token:
            token = os.getenv("DIGITALOCEAN_TOKEN")
        self.token = token

        if not branch:
            branch = sys.argv[1]
        self.branch = branch

        self.release_tag = release_tag
        branch_regex = re.compile("release-*.*")
        if branch_regex.match(self.branch):
            self.release_tag = f"{branch}-unstable"

        random_bit = "".join(random.choice(string.ascii_lowercase) for i in range(4))

        if not name:
            name = f"do-ci-hobby-deploy-{self.release_tag}-{random_bit}"
        self.name = name

        if not hostname:
            hostname = f"{name}.posthog.cc"
        self.hostname = hostname

        self.region = region
        self.image = image
        self.size = size

        self.domain = domain
        self.droplet = droplet
        self.record = record

        self.user_data = (
            f"#!/bin/bash \n"
            "mkdir hobby \n"
            "cd hobby \n"
            "sed -i \"s/#\\$nrconf{restart} = 'i';/\\$nrconf{restart} = 'a';/g\" /etc/needrestart/needrestart.conf \n"
            "git clone https://github.com/PostHog/posthog.git \n"
            "cd posthog \n"
            f"git checkout {branch} \n"
            "cd .. \n"
            f"chmod +x posthog/bin/deploy-hobby \n"
            f"./posthog/bin/deploy-hobby {release_tag} {hostname} 1 \n"
        )

    def block_until_droplet_is_started(self):
        if not self.droplet:
            return
        actions = self.droplet.get_actions()
        up = False
        while not up:
            for action in actions:
                action.load()
                if action.status == "completed":
                    up = True
                    print(action.status)
                else:
                    print("Droplet not booted yet - waiting a bit")
                    time.sleep(5)

    def get_public_ip(self):
        if not self.droplet:
            return
        ip = None
        while not ip:
            time.sleep(1)
            self.droplet.load()
            ip = self.droplet.ip_address
        print(f"Public IP found: {ip}")  # type: ignore
        return ip

    def create_droplet(self, ssh_enabled=False):
        keys = None
        if ssh_enabled:
            manager = digitalocean.Manager(token=self.token)
            keys = manager.get_all_sshkeys()
        self.droplet = digitalocean.Droplet(
            token=self.token,
            name=self.name,
            region=self.region,
            image=self.image,
            size_slug=self.size,
            user_data=self.user_data,
            ssh_keys=keys,
            tags=["ci"],
        )
        self.droplet.create()
        return self.droplet

    def wait_for_instance(self, timeout=20, retry_interval=15):
        if not self.hostname:
            return
        # timeout in minutes
        # return true if success or false if failure
        print("Attempting to reach the instance")
        print(f"We will time out after {timeout} minutes")
        url = f"https://{self.hostname}/_health"
        start_time = datetime.datetime.now()
        while datetime.datetime.now() < start_time + datetime.timedelta(minutes=timeout):
            try:
                # verify is set False here because we are hitting the staging endoint for Let's Encrypt
                # This endpoint doesn't have the strict rate limiting that the production endpoint has
                # This mitigates the chances of getting throttled or banned
                r = requests.get(url, verify=False)
            except Exception as e:
                print(f"Host is probably not up. Received exception\n{e}")
                time.sleep(retry_interval)
                continue
            if r.status_code == 200:
                print("Success - received heartbeat from the instance")
                return True
            print("Instance not ready - sleeping")
            time.sleep(retry_interval)
        print("Failure - we timed out before receiving a heartbeat")
        return False

    def create_dns_entry(self, type, name, data):
        self.domain = digitalocean.Domain(token=self.token, name="posthog.cc")
        self.record = self.domain.create_new_domain_record(type=type, name=name, data=data)
        return self.record

    def create_dns_entry_for_instance(self):
        if not self.droplet:
            return
        self.record = self.create_dns_entry(type="A", name=self.hostname, data=self.get_public_ip())
        return self.record

    def destroy_environment(self, retries=3):
        if not self.droplet or not self.domain or not self.record:
            return
        print("Destroying the droplet")
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                self.droplet.destroy()
                break
            except Exception as e:
                print(f"Could not destroy droplet because\n{e}")
        print("Destroying the DNS entry")
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                self.domain.delete_domain_record(id=self.record["domain_record"]["id"])
                break
            except Exception as e:
                print(f"Could not destroy the dns entry because\n{e}")

    def handle_sigint(self):
        self.destroy_environment()


def main():
    print("Creating droplet on Digitalocean for testing Hobby Deployment")
    ht = HobbyTester()
    signal.signal(signal.SIGINT, ht.handle_sigint)  # type: ignore
    signal.signal(signal.SIGHUP, ht.handle_sigint)  # type: ignore
    signal.signal(signal.SIGTERM, ht.handle_sigint)  # type: ignore
    ht.create_droplet(ssh_enabled=True)
    ht.block_until_droplet_is_started()
    ht.create_dns_entry_for_instance()
    print("Instance has started. You will be able to access it here after PostHog boots (~15 minutes):")
    print(f"https://{ht.hostname}")
    health_success = ht.wait_for_instance()
    ht.destroy_environment()
    if health_success:
        print("We succeeded")
        exit()
    else:
        print("We failed")
        exit(1)


if __name__ == "__main__":
    main()
