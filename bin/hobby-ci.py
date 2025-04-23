#!/usr/local/bin/python

import datetime
import os
import random
import string
import sys
import time

import digitalocean
import requests
from requests.exceptions import SSLError, ConnectionError
from urllib3.exceptions import InsecureRequestWarning
import urllib3

DOMAIN = "posthog.cc"
urllib3.disable_warnings(category=InsecureRequestWarning)


class HobbyTester:
    def __init__(
        self,
        token=None,
        name=None,
        region="sfo3",
        image="ubuntu-22-04-x64",
        size="s-8vcpu-16gb",
        release_tag="latest-release",
        branch=None,
        hostname=None,
        domain=DOMAIN,
        droplet_id=None,
        droplet=None,
        record_id=None,
        record=None,
    ):
        if not token:
            token = os.getenv("DIGITALOCEAN_TOKEN")
        self.token = token
        self.branch = branch
        self.release_tag = release_tag

        random_bit = "".join(random.choice(string.ascii_lowercase) for i in range(4))

        if not name:
            name = f"do-ci-hobby-deploy-{self.release_tag}-{random_bit}"
        self.name = name

        if not hostname:
            hostname = f"{name}.{DOMAIN}"
        self.hostname = hostname

        self.region = region
        self.image = image
        self.size = size

        self.domain = domain
        self.droplet = droplet
        if droplet_id:
            self.droplet = digitalocean.Droplet(token=self.token, id=droplet_id)

        self.record = record
        if record_id:
            self.record = digitalocean.Record(token=self.token, id=record_id)

        self.user_data = (
            f"#!/bin/bash \n"
            "mkdir hobby \n"
            "cd hobby \n"
            "sed -i \"s/#\\$nrconf{restart} = 'i';/\\$nrconf{restart} = 'a';/g\" /etc/needrestart/needrestart.conf \n"
            "git clone https://github.com/PostHog/posthog.git \n"
            "cd posthog \n"
            f"git checkout {self.branch} \n"
            "cd .. \n"
            f"chmod +x posthog/bin/deploy-hobby \n"
            f"./posthog/bin/deploy-hobby {self.release_tag} {self.hostname} 1 \n"
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

    def test_deployment(self, timeout=20, retry_interval=15):
        if not self.hostname:
            return
        # timeout in minutes
        # return true if success or false if failure
        print("Attempting to reach the instance")
        print(f"We will time out after {timeout} minutes")
        url = f"https://{self.hostname}/_health"
        start_time = datetime.datetime.now()
        end_time = start_time + datetime.timedelta(minutes=timeout)
        last_exception = None

        attempt = 0
        while datetime.datetime.now() < end_time:
            attempt += 1
            try:
                # verify is set False here because we are hitting the staging endoint for Let's Encrypt
                # This endpoint doesn't have the strict rate limiting that the production endpoint has
                # This mitigates the chances of getting throttled or banned
                r = requests.get(url, verify=False, timeout=10)
                if r.status_code == 200:
                    print("✅ Success - received heartbeat from the instance")
                    return True
                else:
                    print(f"⚠️ Got non-200 status code: {r.status_code} — retrying")
            except SSLError as ssl_err:
                last_exception = ssl_err
                print(f"🔐 SSL Error on attempt {attempt}: {ssl_err}")
            except ConnectionError as conn_err:
                last_exception = conn_err
                print(f"🔌 Connection Error on attempt {attempt}: {conn_err}")
            except Exception as e:
                last_exception = e
                print(f"❓ Unknown exception on attempt {attempt}: {e}")
            print("💤 Instance not ready - sleeping...")
            time.sleep(retry_interval)

        print("❌ Failure - we timed out before receiving a heartbeat")
        print(f"🧨 Last exception was: {last_exception}")
        return False

    def wait_for_instance_readiness(self, timeout=900, interval=15):
        """
        Waits for the instance to come online by validating TLS, open port 443, and optionally /api/ route.
        """
        import socket
        import ssl

        hostname = self.hostname
        port = 443
        start_time = time.time()

        print(f"🕵️ Waiting up to {timeout}s for TLS and port {port} to be ready on {hostname}...")

        while time.time() - start_time < timeout:
            try:
                context = ssl.create_default_context()
                with socket.create_connection((hostname, port), timeout=10) as sock:
                    with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                        cert = ssock.getpeercert()
                        not_after = cert["notAfter"]
                        print(f"🔐 TLS cert present, expires: {not_after}")
                        break
            except Exception as e:
                print(f"⏳ TLS/port not ready yet: {e}")

            time.sleep(interval)
        else:
            print(f"❌ Timeout after {timeout}s waiting for TLS on {hostname}")
            return False

        # Optional: try basic GET on /api/
        try:
            print(f"🌐 Trying /api/ endpoint on https://{hostname}")
            r = requests.get(f"https://{hostname}/api/", verify=False, timeout=10)
            if r.status_code == 200:
                print("✅ Instance responded at /api/")
                return True
            else:
                print(f"⚠️ Non-200 from /api/: {r.status_code}")
        except Exception as e:
            print(f"🔌 Error connecting to /api/: {e}")

        return True

    def create_dns_entry(self, type, name, data, ttl=30):
        self.domain = digitalocean.Domain(token=self.token, name=DOMAIN)
        self.record = self.domain.create_new_domain_record(type=type, name=name, data=data, ttl=ttl)
        return self.record

    def create_dns_entry_for_instance(self):
        if not self.droplet:
            return
        self.record = self.create_dns_entry(type="A", name=self.name, data=self.get_public_ip())
        return self.record

    def destroy_self(self, retries=3):
        if not self.droplet or not self.domain or not self.record:
            return
        droplet_id = self.droplet.id
        self.destroy_environment(droplet_id, self.domain, self.record["domain_record"]["id"], retries=retries)

    @staticmethod
    def destroy_environment(droplet_id, record_id, retries=3):
        print("Destroying the droplet")
        token = os.getenv("DIGITALOCEAN_TOKEN")
        droplet = digitalocean.Droplet(token=token, id=droplet_id)
        domain = digitalocean.Domain(token=token, name=DOMAIN)
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
                domain.delete_domain_record(id=record_id)
                break
            except Exception as e:
                print(f"Could not destroy the dns entry because\n{e}")

    def handle_sigint(self):
        self.destroy_self()

    def export_droplet(self):
        if not self.droplet:
            print("Droplet not found. Exiting")
            exit(1)
        if not self.record:
            print("DNS record not found. Exiting")
            exit(1)
        record_id = self.record["domain_record"]["id"]
        record_name = self.record["domain_record"]["name"]
        droplet_id = self.droplet.id

        print(f"Exporting the droplet ID: {self.droplet.id} and DNS record ID: {record_id} for name {self.name}")
        env_file_name = os.getenv("GITHUB_ENV")
        with open(env_file_name, "a") as env_file:
            env_file.write(f"HOBBY_DROPLET_ID={droplet_id}\n")
        with open(env_file_name, "a") as env_file:
            env_file.write(f"HOBBY_DNS_RECORD_ID={record_id}\n")
            env_file.write(f"HOBBY_DNS_RECORD_NAME={record_name}\n")
            env_file.write(f"HOBBY_NAME={self.name}\n")

    def ensure_droplet(self, ssh_enabled=True):
        self.create_droplet(ssh_enabled=ssh_enabled)
        self.block_until_droplet_is_started()
        self.create_dns_entry_for_instance()
        self.export_droplet()

        print("⏳ Waiting 60 seconds to allow droplet to stabilize...")
        time.sleep(60)


def main():
    command = sys.argv[1]
    if command == "create":
        print("Creating droplet on Digitalocean for testing Hobby Deployment")
        ht = HobbyTester()
        ht.ensure_droplet(ssh_enabled=True)
        print("Instance has started. You will be able to access it here after PostHog boots (~15 minutes):")
        print(f"https://{ht.hostname}")

    if command == "destroy":
        print("Destroying droplet on Digitalocean for testing Hobby Deployment")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        domain_record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        print(f"Droplet ID: {droplet_id}")
        print(f"Record ID: {domain_record_id}")
        HobbyTester.destroy_environment(droplet_id=droplet_id, record_id=domain_record_id)

    if command == "test":
        if len(sys.argv) < 3:
            print("Please provide the branch name to test")
            exit(1)
        branch = sys.argv[2]
        name = os.environ.get("HOBBY_NAME")
        record_id = os.environ.get("HOBBY_DNS_RECORD_ID")
        droplet_id = os.environ.get("HOBBY_DROPLET_ID")
        print(f"Testing the deployment for {name} on branch {branch}")
        print(f"Record ID: {record_id}")
        print(f"Droplet ID: {droplet_id}")

        ht = HobbyTester(
            branch=branch,
            name=name,
            record_id=record_id,
            droplet_id=droplet_id,
        )

        # 🔍 New: Wait for TLS readiness and basic API responsiveness
        ready = ht.wait_for_instance_readiness()
        if not ready:
            print("⚠️ Droplet didn't become ready for TLS + basic API — skipping test.")
            exit(1)

        # 🧪 Proceed with /_health check only if readiness probe passed
        health_success = ht.test_deployment()
        if health_success:
            print("We succeeded")
            exit()
        else:
            print("We failed")
            exit(1)


if __name__ == "__main__":
    main()
