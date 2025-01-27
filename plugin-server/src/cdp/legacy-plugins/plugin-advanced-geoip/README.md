This plugin is deprecated, use IP anonymisation in project settings with geoIP app to remove IP. Use filter out plugin to remove any geo info not wanted.

<img src="logo.png" alt="Advanced GeoIP logo" width="120px" />

# PostHog Community App: Advanced GeoIP

This app extends functionality for the [GeoIP app](https://github.com/PostHog/posthog-plugin-geoip). This functionality cannot be part of the main GeoIP app as that app is stateless:

1. Enables discarding IP addresses after GeoIP lookup is processed. This is particularly helpful for privacy preservation and compliance. IP addresses are considered PII in several countries.
2. Enables discarding entire GeoIP information for events that come from certain libraries. For example, you probably don't want to assign locations to users that belong to your server. I've used it to ignore IP address and GeoIP information from my backend.

## 🚀 Usage

To use it simply install the app from the repository URL: https://github.com/paolodamico/posthog-app-advanced-geoip or search for it in the PostHog App Library.

## 🧑‍💻 Development & testing

Contributions are welcomed! Feel free to open a PR or an issue. To develop locally and contribute to this package, you can simply follow these instructions after cloning the repo.

-   Install dependencies
    ```bash
    yarn install
    ```
-   Run tests
    ```bash
    yarn test
    ```
-   Install app in your local instance by going to `/project/apps` in your PostHog instance, clicking on the "Advanced" tab and entering the full path where you cloned the repo. Please note that running apps locally on PostHog is currently buggy (see [posthog#7170](https://github.com/PostHog/posthog/issues/7170)).

## 🧑‍⚖️ License

This repository is MIT licensed. Please review the LICENSE file in this repository.

Copyright (C) 2022 Paolo D'Amico.
