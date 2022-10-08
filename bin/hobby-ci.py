#!/usr/local/bin/python

# doctl compute droplet create --image ubuntu-22-04-x64 --user-data '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby) latest-release hobby.posthog.cc"' --size s-4vcpu-8gb --region sfo3 --tag-name ci hobby-e2e-ci-test 
# doctl compute droplet get pjhul-test -o json | jq '.[0].networks.v4[] | select(.type=="private") | .ip_address'
# doctl compute domain records create posthog.cc --record-name hobby-cli --record-type A --record-data 8.8.8.8
# doctl compute droplet delete hobby-e2e-ci-test --force
# doctl compute domain records delete posthog.cc 341175450 --force

import digitalocean
import random
import string
import time
import os

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
				time.sleep(1)


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
# droplet.destroy()
