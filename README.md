# Posthog

PostHog is self-hosted product analytics. Automate the collection of every event on your website or app, and stay in control of your users’ data.

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

Using the [posthog/posthog:latest](https://hub.docker.com/repository/docker/posthog/posthog/general) Docker image.

**On Ubuntu**

1. [Install Docker](https://docs.docker.com/installation/ubuntulinux/)
2. [Install Docker Compose](https://docs.docker.com/compose/install/)
3.
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
3. 
```bash
git clone https://github.com/posthog/posthog.git
yarn build
pip install -r requirements.txt
gunicorn posthog.wsgi --config gunicorn.config.py --log-file -
```


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
10) Run `python manage.py runserver`

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
* When pushing to github make sure you push your branch name and not master!!