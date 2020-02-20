# PostHog

PostHog helps developers to understand how their applications are used.

PostHog is open source product analytics, built for developers. Automate the collection of every event on your website or app, with no need to send data to 3rd parties. It's a 1 click to deploy on your own infrastructure, with full API/SQL access to the underlying data.

## Quick start

1 click Heroku deploy:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/posthog/posthog)

See [PostHog docs](https://github.com/PostHog/posthog/wiki) for in-depth walk throughs on functionality.

![PostHog dashboard screenshot](https://posthog.com/wp-content/uploads/2020/02/Screenshot-2020-02-13-at-23.14.36-2.png)

## Features

- **Event-based** analytics at a user level - see which users are doing what in your application.
- **Complete control** over your data -- host it yourself.
- **Automatically capture** clicks and page views to do analyze what your users are doing **retroactively**. 
- Libraries for **[JS](https://github.com/PostHog/posthog/wiki/JS-integration), [Python](https://github.com/PostHog/posthog/wiki/python-integration), [Ruby](https://github.com/PostHog/posthog/wiki/ruby-integration)** + API for anything else.
- Beautiful **graphs, funnels and dashboards**.
- Super easy deploy using **Docker** or **Heroku**.

## Philosophy

Many engineers find it tough to work out how their products are being used. This makes design decisions tough. PostHog solves that.

We also strongly believe 3rd party analytics don't work anymore in a world of Cookie laws, GDPR, CCPA and lots of other 4 letter acronyms. There should be an alternative to sending all of your users' personal information and usage data to 3rd parties.

PostHog gives you full control over all your users' data, while letting anyone easily perform powerful analytics.

It means you can know who is using your app, how they're using, and where you lose users in the sign up process.

## What's cool about this?

PostHog is the only <strong>product-focused</strong> open source analytics library, with an event and user-driven architecture. That means tracking identifiable (where applicable) user behavior, and creating user profiles. We are an open source alternative to Mixpanel, Amplitude or Heap, designed to be more developer friendly.

There are a couple of session-based open source libraries that are nice alternatives to Google Analytics. That's not what we are focused on.

## One-line docker preview

```bash
docker run -t -i --rm --publish 8000:8000 -v postgres:/var/lib/postgresql posthog/posthog:preview
```

This image has everything you need to try out PostHog locally! It will set up a server on http://127.0.0.1:8000.

## Deploy to Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/posthog/posthog)

## Production installation

The preview image has Postgres running locally and runs in debug mode.

For a production installation you have a few options:

### Deploy to Heroku

Heroku is the quickest way to get a production PostHog environment up-and-running.

We recommend getting at the very least a `hobby-dev` Postgres and Dyno for low volumes of events.

### Docker

Using the [posthog/posthog:latest](https://hub.docker.com/r/posthog/posthog) Docker image.

**On Ubuntu**

1. [Install Docker](https://docs.docker.com/installation/ubuntulinux/)
2. [Install Docker Compose](https://docs.docker.com/compose/install/)
3. Run the following:
```bash
sudo apt-get install git
git clone https://github.com/posthog/posthog.git
cd posthog
docker-compose build
docker-compose up -d
```

### From source
1. Make sure you have Python >= 3.7 and pip installed
2. [Install Yarn](https://classic.yarnpkg.com/en/docs/install/#mac-stable)
3. Run the following:
```bash
git clone https://github.com/posthog/posthog.git
yarn build
pip install -r requirements.txt
gunicorn posthog.wsgi --config gunicorn.config.py --log-file -
```

### Running behind a proxy?
Make sure you set the `IS_BEHIND_PROXY` environment variable which will set the HTTP_X_FORWARDED_PROTO header.

# Development
## Running backend (Django)
1) Make sure you have python 3 installed `python3 --version`
2) Make sure you have postgres installed `brew install postgres`
3) Start postgres, run `brew services start postgresql`
4) Create Database `createdb posthog`
5) Navigate into the correct folder `cd posthog`
6) Run `python3 -m venv env` (creates virtual environment in current direction called 'env')
7) Run `source env/bin/activate` (activates virtual environment)
8) Run `pip install -r requirements.txt`. If you have problems with this step (TLS/SSL error), then run `~ brew update && brew upgrade` followed by `python3 -m pip install --upgrade pip`, then retry the requirements.txt install.
9) Run migrations `python manage.py migrate`
10) Run `DEBUG=1 python manage.py runserver`
11) Run the tests and frontend

## Running backend tests
`bin/tests`

## Running frontend (React)

If at any point, you get "command not found: nvm", you need to install nvm, then use that to install node.

1) Make sure you are running Django above in a separate terminal
2) Now run `bin/start-frontend`
3) Optional: If you're making changes to the editor, you'll need to do `cd frontend && yarn start-editor` to watch changes.

## Create a new branch
If you are working on some changes, please create a new branch, submit it to github ask for approval and when it gets approved it should automatically ship to Heroku

* Before writing anything run `git pull origin master`
* Then create your branch `git checkout -b %your_branch_name%` call your branch something that represents what you're planning to do
* When you're finished add your changes `git add .`
* And commit with a message `git commit -m "%your feature description%" `
* When pushing to github make sure you push your branch name and not master! Use `git push origin %your_branch_name%`

# Open source / Paid

This repo is entirely MIT licensed. We charge for things like teams, permissioning, data lake integrations, and support. Please email hey@posthog.com and we will gladly help with your implementation.
