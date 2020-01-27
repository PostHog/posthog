# Posthog

## Running locally
1) Make sure you have python 3 installed `python3 --version`
2) Make sure you have postgres installed `brew install postgres`
3) Start postgres, run `brew services start postgresql`
4) Create Database `createdb posthog`
5) Navigate into the correct folder `cd posthog`
6) Run `python3 -m venv env` (creates virtual environment in current direction called 'env')
7) Run `source env/bin/activate` (activates virtual environment)
8) Run `pip install -r requirements.txt`. If you have problems with this step (TLS/SSL error), then run `~ brew update && brew upgrade` followed by `python3 -m pip install --upgrade pip`, then retry the requirements.txt install.
9) Run migrations `python manage.py migrate`
10) Run `python manage.py createsuperuser`
11) Create a username, email and password
12) Run `python manage.py runserver`
13) If you get an error on loading https://127.0.0.1:8000 (which Chrome will default to) - "you're accessing the dev server over HTTPS, but it only supports HTTP", then go to settings.py and set `SECURE_SSL_REDIRECT = False`

## Running tests
`bin/tests`

## Running frontend

If at any point, you get "command not found: nvm", you need to install nvm, then use that to install node.

1) Make sure you are running Django above in a separate terminal
2) Go to the frontend directory, `cd frontend`
3) Run `yarn install`
4) Now run `bin/start-frontend`

## Pulling production database locally

`bin/pull_production_db`

## Create a new branch
If you are working on some changes, please create a new branch, submit it to github ask for approval and when it gets approved it should automatically ship to Heroku

* Before writing anything run `git pull origin master`
* Then create your branch `git checkout -b %your_branch_name%` call your branch something that represents what you're planning to do
* When you're finished add your changes `git add .`
* And commit with a message `git commit -m "%your feature description%" `
* When pushing to github make sure you push your branch name and not master!!

## Deployment to Heroku

* `git push origin %branch_name%` (sends it to Github) - DO NOT use `git push heroku master`
* Be very careful running migrations by testing if they work locally first (ie run makemigrations, migrate, runserver locally when you've made database changes)
* James or Tim will approve your change, and will deploy it to master
