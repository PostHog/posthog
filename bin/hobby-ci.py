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

letters = string.ascii_lowercase
random_bit = "".join(random.choice(letters) for i in range(4))
name = f"do-ci-hobby-deploy-{random_bit}"
region = "sfo3"
image = "ubuntu-22-04-x64"
size = "s-4vcpu-8gb"
release_tag = "latest-release"
branch_regex = re.compile("release-*.*")
branch = sys.argv[1]
if branch_regex.match(branch):
    release_tag = f"{branch}-unstable"
hostname = f"{name}.posthog.cc"
user_data = (
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
token = os.getenv("DIGITALOCEAN_TOKEN")


class HobbyTester:
    def __init__(self, domain, droplet, record):
        # Placeholders for DO resources
        self.domain = domain
        self.droplet = droplet
        self.record = record

    @staticmethod
    def block_until_droplet_is_started(droplet):
        actions = droplet.get_actions()
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

    @staticmethod
    def get_public_ip(droplet):
        ip = None
        while not ip:
            time.sleep(1)
            droplet.load()
            ip = droplet.ip_address
        print(f"Public IP found: {ip}")  # type: ignore
        return ip

    @staticmethod
    def create_droplet(ssh_enabled=False):
        keys = None
        if ssh_enabled:
            manager = digitalocean.Manager(token=token)
            keys = manager.get_all_sshkeys()
        droplet = digitalocean.Droplet(
            token=token,
            name=name,
            region=region,
            image=image,
            size_slug=size,
            user_data=user_data,
            ssh_keys=keys,
            tags=["ci"],
        )
        droplet.create()
        return droplet

    @staticmethod
    def wait_for_instance(hostname, timeout=20, retry_interval=15):
        # timeout in minutes
        # return true if success or false if failure
        print("Attempting to reach the instance")
        print(f"We will time out after {timeout} minutes")
        url = f"https://{hostname}/_health"
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

    @staticmethod
    def destroy_environment(droplet, domain, record, retries=3):
        print("Destroying the droplet")
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                droplet.destroy()
                break
            except Exception as e:
                print(f"Could not destroy droplet because\n{e}")
        print("Destroying the DNS entry")
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                domain.delete_domain_record(id=record["domain_record"]["id"])
                break
            except Exception as e:
                print(f"Could not destroy the dns entry because\n{e}")

    def handle_sigint(self):
        self.destroy_environment(self.droplet, self.domain, self.record)


def main():
    print("Creating droplet on Digitalocean for testing Hobby Deployment")
    droplet = HobbyTester.create_droplet(ssh_enabled=True)
    HobbyTester.block_until_droplet_is_started(droplet)
    public_ip = HobbyTester.get_public_ip(droplet)
    domain = digitalocean.Domain(token=token, name="posthog.cc")
    record = domain.create_new_domain_record(type="A", name=name, data=public_ip)

    hobby_tester = HobbyTester(domain, droplet, record)
    signal.signal(signal.SIGINT, hobby_tester.handle_sigint)  # type: ignore
    signal.signal(signal.SIGHUP, hobby_tester.handle_sigint)  # type: ignore
    print("Instance has started. You will be able to access it here after PostHog boots (~15 minutes):")
    print(f"https://{hostname}")
    health_success = HobbyTester.wait_for_instance(hostname)
    HobbyTester.destroy_environment(droplet, domain, record)
    if health_success:
        print("We succeeded")
        exit()
    else:
        print("We failed")
        exit(1)


if __name__ == "__main__":
    main()
