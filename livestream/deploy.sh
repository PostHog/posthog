#!/bin/bash

env GOOS=linux GOARCH=arm64 go build -o dist/livestream
scp dist/livestream ubuntu@172.31.40.65:

