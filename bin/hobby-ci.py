#!/usr/local/bin/python
# ruff: noqa: T201 allow print statements

import os
import sys
import time
import random
import string
import datetime

import urllib3
import requests
import digitalocean

DOMAIN = "posthog.cc"


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
            "set -e \n"
            'LOG_PREFIX="[$(date \\"+%Y-%m-%d %H:%M:%S\\")]" \n'
            'echo "$LOG_PREFIX Cloud-init deployment starting" \n'
            "mkdir hobby \n"
            "cd hobby \n"
            'echo "$LOG_PREFIX Setting up needrestart config" \n'
            "sed -i \"s/#\\$nrconf{restart} = 'i';/\\$nrconf{restart} = 'a';/g\" /etc/needrestart/needrestart.conf \n"
            'echo "$LOG_PREFIX Cloning PostHog repository" \n'
            "git clone https://github.com/PostHog/posthog.git \n"
            "cd posthog \n"
            f'echo "$LOG_PREFIX Using branch: {self.branch}" \n'
            f"git checkout {self.branch} \n"
            "CURRENT_COMMIT=$(git rev-parse HEAD) \n"
            'echo "$LOG_PREFIX Current commit: $CURRENT_COMMIT" \n'
            "cd .. \n"
            f"chmod +x posthog/bin/deploy-hobby \n"
            'echo "$LOG_PREFIX Starting deployment script" \n'
            f'if [ "{self.branch}" != "main" ] && [ "{self.branch}" != "master" ] && [ -n "{self.branch}" ]; then \n'
            f'    echo "$LOG_PREFIX Using commit hash for feature branch deployment" \n'
            f"    ./posthog/bin/deploy-hobby $CURRENT_COMMIT {self.hostname} 1 \n"
            f"else \n"
            f'     echo "$LOG_PREFIX Installing PostHog version: {self.release_tag}" \n'
            f"    ./posthog/bin/deploy-hobby {self.release_tag} {self.hostname} 1 \n"
            f"fi \n"
            "DEPLOY_EXIT=$? \n"
            'echo "$LOG_PREFIX Deployment script exited with code: $DEPLOY_EXIT" \n'
            "exit $DEPLOY_EXIT \n"
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

    def get_droplet_info(self):
        """Fetch droplet information from DigitalOcean API for debugging"""
        if not self.droplet or not self.token:
            return None
        try:
            self.droplet.load()
            return {
                "id": self.droplet.id,
                "name": self.droplet.name,
                "status": self.droplet.status,
                "ip": self.droplet.ip_address,
                "memory": self.droplet.memory,
                "vcpus": self.droplet.vcpus,
                "disk": self.droplet.disk,
                "created_at": self.droplet.created_at,
            }
        except Exception as e:
            print(f"Could not fetch droplet info: {e}")
            return None

    def get_droplet_kernel_logs(self):
        """Attempt to get kernel logs from droplet via API"""
        if not self.droplet or not self.token:
            return None
        try:
            # Try to get serial console output (requires the droplet to have it enabled)
            url = f"https://api.digitalocean.com/v2/droplets/{self.droplet.id}/console"
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("console_output")
        except Exception as e:
            print(f"Could not fetch kernel logs: {e}")
        return None

    def test_deployment(self, timeout=30, retry_interval=15):
        if not self.hostname:
            return
        # timeout in minutes
        # return true if success or false if failure
        print("Attempting to reach the instance")
        print(f"We will time out after {timeout} minutes")

        # Suppress SSL warnings for staging Let's Encrypt certificates
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        url = f"https://{self.hostname}/_health"
        start_time = datetime.datetime.now()
        attempt = 1
        last_error = None
        http_502_count = 0
        connection_error_count = 0

        while datetime.datetime.now() < start_time + datetime.timedelta(minutes=timeout):
            print(f"Trying to connect... (attempt {attempt})")
            try:
                # verify is set False here because we are hitting the staging endpoint for Let's Encrypt
                # This endpoint doesn't have the strict rate limiting that the production endpoint has
                # This mitigates the chances of getting throttled or banned
                r = requests.get(url, verify=False, timeout=10)
            except Exception as e:
                last_error = type(e).__name__
                connection_error_count += 1
                print(f"Connection failed: {type(e).__name__}")
                time.sleep(retry_interval)
                attempt += 1
                continue
            if r.status_code == 200:
                print("Success - received heartbeat from the instance")
                return True
            if r.status_code == 502:
                http_502_count += 1
            print(f"Instance not ready (HTTP {r.status_code}) - sleeping")
            time.sleep(retry_interval)
            attempt += 1

        # Health check failed - try to gather diagnostic info
        print("\nFailure - we timed out before receiving a heartbeat")
        print("\n📋 Attempting to gather diagnostic information...")

        droplet_info = self.get_droplet_info()
        if droplet_info:
            print(f"\n🖥️  Droplet Status:")
            for key, value in droplet_info.items():
                print(f"  {key}: {value}")

        kernel_logs = self.get_droplet_kernel_logs()
        if kernel_logs:
            print(f"\n📝 Kernel/Console Output (last 500 chars):")
            print(kernel_logs[-500:] if len(kernel_logs) > 500 else kernel_logs)

        # Provide diagnostic summary
        print(f"\n🔍 Failure Pattern Analysis:")
        print(f"  - Connection errors: {connection_error_count}")
        print(f"  - HTTP 502 (bad gateway): {http_502_count}")
        print(f"  - Last error: {last_error}")

        if http_502_count > 0:
            print("  💡 502 errors suggest nginx/caddy is up but the app isn't responding")
            print("     Check cloud-init logs for deployment failures")
        if connection_error_count > 0 and http_502_count == 0:
            print("  💡 Connection errors suggest the web service never started")
            print("     Check if Docker containers are running")

        print(f"\n📍 For manual debugging, SSH to: ssh root@{self.droplet.ip_address if self.droplet else '?'}")
        print(f"    Then check: tail -f /var/log/cloud-init-output.log")
        print(f"    And: docker-compose logs")

        return False

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

        # Attempt to destroy droplet
        droplet_destroyed = False
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                droplet.destroy()
                droplet_destroyed = True
                print("✅ Droplet destroyed successfully")
                break
            except Exception as e:
                print(f"⚠️  Attempt {attempts}/{retries + 1} - Could not destroy droplet: {type(e).__name__}")
                if attempts <= retries:
                    time.sleep(2)  # Wait before retry
                else:
                    print(f"❌ Failed to destroy droplet after {retries + 1} attempts")

        # Attempt to destroy DNS record
        dns_destroyed = False
        print("Destroying the DNS entry")
        attempts = 0
        while attempts <= retries:
            attempts += 1
            try:
                domain.delete_domain_record(id=record_id)
                dns_destroyed = True
                print("✅ DNS record destroyed successfully")
                break
            except Exception as e:
                print(f"⚠️  Attempt {attempts}/{retries + 1} - Could not destroy DNS record: {type(e).__name__}")
                if attempts <= retries:
                    time.sleep(2)  # Wait before retry
                else:
                    print(f"❌ Failed to destroy DNS record after {retries + 1} attempts")

        # Fail loudly if either cleanup failed
        if not droplet_destroyed or not dns_destroyed:
            error_msg = []
            if not droplet_destroyed:
                error_msg.append(f"droplet {droplet_id}")
            if not dns_destroyed:
                error_msg.append(f"DNS record {record_id}")
            raise Exception(f"⚠️  Failed to destroy {' and '.join(error_msg)} - manual cleanup may be required")

        print("\n✅ Cleanup completed successfully")

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
        health_success = ht.test_deployment()
        if health_success:
            print("We succeeded")
            exit()
        else:
            print("We failed")
            exit(1)


if __name__ == "__main__":
    main()
