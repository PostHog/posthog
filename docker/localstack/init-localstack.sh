#!/bin/bash

awslocal s3 mb s3://posthog 2>/dev/null || true

