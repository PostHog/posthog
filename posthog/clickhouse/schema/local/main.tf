# Puts every schema group on one ClickHouse server: the layout for local development, tests, CI and
# self-hosted installs. Run it through bin/clickhouse-schema, which supplies the provider and the variables.

terraform {
  required_version = ">= 1.8"

  required_providers {
    clickhousedbops = {
      source = "PostHog/clickhousedbops"
      # Keep equal to provider-version.txt, which bin/clickhouse-schema downloads.
      version = "0.5.1"
    }
  }

  backend "local" {}
}

provider "clickhousedbops" {
  protocol = var.protocol
  host     = var.host
  port     = var.port

  auth_config = {
    strategy = "password"
    username = var.username
    password = var.password == "" ? null : var.password
  }

  # No state is kept for test databases and fresh checkouts, so objects that already exist are taken over.
  adopt_existing = true

  # Dictionary passwords are compared like the rest of the source. The server needs
  # display_secrets_in_show_and_select, which docker/clickhouse/config.d/default.xml sets.
  manage_dictionary_passwords = true
}

