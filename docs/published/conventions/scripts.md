---
title: Consistent scripts to rule them all
sidebar: Handbook
---

PostHog has 235 (at the time of writing) public repositories. Each of these repositories has a unique way to get the project up and running locally. To limit the friction of this we adapt GitHub's approach of [scripts to rule them all](https://github.blog/engineering/engineering-principles/scripts-to-rule-them-all/). As they say:

> Being able to get from git clone to an up-and-running project in a development environment is imperative for fast, reliable contributions.

Not every repository will need every script. Some repositories will need scripts custom to the environment (for example, `make` files). That's all fine. The goal is to have a baseline set of scripts that we can use to get a development environment up and a known location to look for those scripts.

## Standard scripts at PostHog

When starting a new project, create a `bin` directory and include the following scripts (when relevant):

* `bin/setup` - Install or upgrade dependencies (Ex. npm packages, brew packages, etc. Usually run once after cloning the repository and occasionally to upgrade packages).
* `bin/update` - Updates dependencies after a pull. This could simply call `bin/setup`.
* `bin/build` - Build the project, for projects that are compiled such as C#, Java, etc.
* `bin/start` - Start the project. For SDKs, this might start an example server.
* `bin/test` - Run tests (Ex. `npm test`, `bundle exec rspec`, etc.). Also includes linting, formatting, etc.
* `bin/fmt` - Optional: Format/lint code. This can be called by `test`.
* `bin/docs` - Optional: Generate documentation artifacts like API and SDK references.

> **Warning:** Some environments add `bin` to the `.gitignore` file by default because that's where they compile binaries to.

Example scripts are available in the [PostHog/scripts](https://github.com/PostHog/scripts) repository.