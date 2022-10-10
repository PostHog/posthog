#!/usr/local/bin/python

import datetime
import random
import string
import time
import os

import digitalocean
import requests


letters = string.ascii_lowercase
random_bit = ''.join(random.choice(letters) for i in range(4))
name = f"do-ci-hobby-deploy-{random_bit}"
region = 'sfo3'
image = 'ubuntu-22-04-x64'
size = 's-4vcpu-8gb'
release_tag = 'latest-release'
hostname = f'{name}.posthog.cc'
user_data = f'#!/bin/bash \n' \
			f'wget https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby \n' \
			f'chmod +x deploy-hobby \n' \
			f'./deploy-hobby {release_tag} {hostname}\n'
token = os.getenv("DIGITALOCEAN_ACCESS_TOKEN")


def block_until_droplet_is_started(droplet):
	actions = droplet.get_actions()
	up = False
	while not up:
		for action in actions:
			action.load()
			if action.status == 'completed':
				up = True
				print(action.status)
			else:
				print("Droplet not booted yet - waiting a bit")
				time.sleep(5)


def get_public_ip(droplet):
	ip = None
	while not ip:
		time.sleep(1)
		droplet.load()
		ip = droplet.ip_address
	print(f"Public IP found: {ip}")
	return ip


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
		tags=['ci']
	)
	droplet.create()
	return droplet


def waitForInstance(hostname, timeout=10):
	# timeout in minutes
	# return true if success or false if failure
	print("Attempting to reach the instance")
	print(f"We will time out after {timeout} minutes")
	url = f"https://{hostname}/_health"
	timeout_seconds = timeout * 60
	start_time = datetime.datetime.now()
	while True:
		try:
			r = requests.get(url)
		except Exception as e:
			print(f"Host is probably not up. Received exception\n{e}")
			time.sleep(10)
			continue
		elapsed = datetime.datetime.now() - start_time
		if r.status_code == 200:
			print("Success - received heartbeat from the instance")
			return True
		if elapsed.seconds >= timeout_seconds:
			print("Failure - we timed out before receiving a heartbeat")
			return False
		print("Instance not ready - sleeping")
		time.sleep(3)

def main():
	print("Creating droplet on Digitalocean for testing Hobby Deployment")
	droplet = create_droplet(ssh_enabled=True)
	block_until_droplet_is_started(droplet)
	public_ip = get_public_ip(droplet)
	domain = digitalocean.Domain(token=token, name="posthog.cc")
	new_record = domain.create_new_domain_record(
		type='A',
		name=name,
		data=public_ip
	)
	print("Instance has started. You can access it here:")
	print(f"https://{hostname}")
	health_success = waitForInstance(hostname)
	print("Destroying the droplet")
	droplet.destroy()
	print("Destroying the DNS entry")
	domain.delete_domain_record(new_record)
	if health_success:
		exit(1)
	else:
		exit(666)


if __name__ == "__main__":
	main()
