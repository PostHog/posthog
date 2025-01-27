# PostHog Plugin: Hello World Starter Kit

[![License: MIT](https://img.shields.io/badge/License-MIT-red.svg?style=flat-square)](https://opensource.org/licenses/MIT)

This is a basic exemplary PostHog plugin. It adds property `"greeting"` to every event, with a configurable value (default: `"Hello world!"`).

Feel free to use it as a base for your own plugins!

## How to develop

All of the plugin's code is located in the `index.js` file, which is JavaScript ran inside of PostHog.
To get yourself up to speed with this environment, we sincerely recommend checking out our [Plugins overview in PostHog Docs]([the Plugins Overview](https://posthog.com/docs/plugins/build/overview).
For a crash course, read our [plugin building tutorial in PostHog Docs](https://posthog.com/docs/plugins/build/tutorial).

## How to test

To test the plugin, you'll need to install a few `npm` dependencies already specified in `package.json`:
```bash
npm install
```

This will get you the testing library Jest and some our test helpers.
Then to run tests it's just:

```bash
npm test
```

## How to install

1. Open PostHog.
1. Open the "Data pipelines" page from the sidebar.
1. Head to the "Apps management" tab.
1. "Install from GitHub, GitLab or npm" using this repository's URL.

## Questions?

### [Join our Slack community.](https://join.slack.com/t/posthogusers/shared_invite/enQtOTY0MzU5NjAwMDY3LTc2MWQ0OTZlNjhkODk3ZDI3NDVjMDE1YjgxY2I4ZjI4MzJhZmVmNjJkN2NmMGJmMzc2N2U3Yjc3ZjI5NGFlZDQ)

We're here to help you with anything PostHog!
