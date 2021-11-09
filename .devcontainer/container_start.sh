#!/bin/bash
#set -e

apt-get remove -y docker docker.io containerd runc
apt-get update
apt install -y docker.io
apt autoremove -y
echo "printf 'Hello 🦔! To start PostHog run this:\n "./ee/bin/docker-ch-dev-web"\n'" > ~/.bashrc