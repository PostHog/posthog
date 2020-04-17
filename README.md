![PostHog header](https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/github-cover.png)

# PostHog (Community Edition)

PostHog is open source product analytics, built for developers. Automate the collection of every event on your website or app, with no need to send data to 3rd parties. It's a 1 click to deploy on your own infrastructure, with full API/SQL access to the underlying data.

## Quick start

1-click Heroku deploy:

<a href="https://heroku.com/deploy?template=https://github.com/posthog/posthog"><img src="https://www.herokucdn.com/deploy/button.svg" width="250px" /></a>

See [PostHog docs](https://docs.posthog.com) for in-depth walk throughs on functionality.

![PostHog dashboard screenshot](https://posthog.com/wp-content/uploads/2020/02/Screenshot-2020-02-13-at-23.14.36-2.png)

Join the [PostHog Users Slack](https://join.slack.com/t/posthogusers/shared_invite/enQtOTY0MzU5NjAwMDY3LTc2MWQ0OTZlNjhkODk3ZDI3NDVjMDE1YjgxY2I4ZjI4MzJhZmVmNjJkN2NmMGJmMzc2N2U3Yjc3ZjI5NGFlZDQ) if you need help, want to chat, or are thinking of a new feature idea.

## Features

-   **Event-based** analytics at a user level - see which users are doing what in your application.
-   **Complete control** over your data - host it yourself.
-   **Automatically capture** clicks and page views to do analyze what your users are doing **retroactively**.
-   Libraries for **[JS](https://docs.posthog.com/#/integrations/js-integration), [Python](https://docs.posthog.com/#/integrations/python-integration), [Ruby](https://docs.posthog.com/#/integrations/ruby-integration), [Node](https://docs.posthog.com/#/integrations/node-integration), [Go](https://docs.posthog.com/#/integrations/go-integration)** + [API](https://docs.posthog.com/#/integrations/api) for anything else.
-   Beautiful **[graphs](https://docs.posthog.com/#/features/trends), [funnels](https://docs.posthog.com/#/features/funnels), [user cohorts](https://docs.posthog.com/#/features/cohorts), [user paths](https://docs.posthog.com/#/features/paths) and [dashboards](https://docs.posthog.com/#/features/dashboards)**.
-   Super easy deploy using **Docker** or **Heroku**.

## Event autocapture

<img src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Website-Assets/Creating+new+action+with+toolbar.gif" width="100%">

## Philosophy

Many engineers find it painful to work out how their products are being used. This makes design decisions tough. PostHog solves that.

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

## Production deployment

[See docs for production deployment](https://docs.posthog.com/#/deployment)

## Development

### Running PostHog

1. Make sure you have python 3 installed `python3 --version`
2. Make sure you have redis installed and running `brew install redis && brew services start redis`
3. Make sure you have postgres installed and running `brew install postgres && brew services start postgresql`
4. Create Database `createdb posthog`
5. Navigate into the correct folder `cd posthog`
6. Run `python3 -m venv env` (creates virtual environment in current direction called 'env')
7. Run `source env/bin/activate` (activates virtual environment)
8. Run `pip install -r requirements.txt`. If you have problems with this step (TLS/SSL error), then run `~ brew update && brew upgrade` followed by `python3 -m pip install --upgrade pip`, then retry the requirements.txt install.
9. Run migrations `DEBUG=1 python3 manage.py migrate`
10. Run `DEBUG=1 ./bin/start` to start the backend, worker and frontend simultaneously

Now open [http://localhost:8000](http://localhost:8000) to see the app.

To see some data on the frontend, you should go to the `http://localhost:8000/demo` and play around with it, so you can see some data on dashboard

### Running backend separately (Django)

Run `DEBUG=1 ./bin/start-backend`

### Running background worker separately (Celery)

Run `DEBUG=1 ./bin/start-worker`

### Running frontend separately (React)

If at any point, you get "command not found: nvm", you need to install nvm, then use that to install node.

Run `./bin/start-frontend`

### Running backend tests

Run `./bin/tests`

## Open source / Paid

This repo is entirely [MIT licensed](/LICENSE). We charge for things like user permissioning and auditability, a/b testing and dedicated support. Please email hey@posthog.com and we will gladly help with your implementation.

## Contributors 🦸

[//]: contributor-faces

<a href="https://github.com/timgl"><img src="https://avatars1.githubusercontent.com/u/1727427?v=4" title="timgl" width="80" height="80"></a>
<a href="https://github.com/mariusandra"><img src="https://avatars2.githubusercontent.com/u/53387?v=4" title="mariusandra" width="80" height="80"></a>
<a href="https://github.com/jamesefhawkins"><img src="https://avatars3.githubusercontent.com/u/47497682?v=4" title="jamesefhawkins" width="80" height="80"></a>
<a href="https://github.com/EDsCODE"><img src="https://avatars0.githubusercontent.com/u/13127476?v=4" title="EDsCODE" width="80" height="80"></a>
<a href="https://github.com/bhavish-agarwal"><img src="https://avatars3.githubusercontent.com/u/14195048?v=4" title="bhavish-agarwal" width="80" height="80"></a>
<a href="https://github.com/gzog"><img src="https://avatars0.githubusercontent.com/u/1487006?v=4" title="gzog" width="80" height="80"></a>
<a href="https://github.com/Tmunayyer"><img src="https://avatars2.githubusercontent.com/u/29887304?v=4" title="Tmunayyer" width="80" height="80"></a>
<a href="https://github.com/Tannergoods"><img src="https://avatars1.githubusercontent.com/u/60791437?v=4" title="Tannergoods" width="80" height="80"></a>
<a href="https://github.com/03difoha"><img src="https://avatars3.githubusercontent.com/u/8876615?v=4" title="03difoha" width="80" height="80"></a>
<a href="https://github.com/iMerica"><img src="https://avatars3.githubusercontent.com/u/487897?v=4" title="iMerica" width="80" height="80"></a>
<a href="https://github.com/pedroapfilho"><img src="https://avatars2.githubusercontent.com/u/13142568?v=4" title="pedroapfilho" width="80" height="80"></a>
<a href="https://github.com/budnik"><img src="https://avatars0.githubusercontent.com/u/1160699?v=4" title="budnik" width="80" height="80"></a>
<a href="https://github.com/elliebike"><img src="https://avatars1.githubusercontent.com/u/53315310?v=4" title="elliebike" width="80" height="80"></a>
<a href="https://github.com/tirkarthi"><img src="https://avatars3.githubusercontent.com/u/3972343?v=4" title="tirkarthi" width="80" height="80"></a>
<a href="https://github.com/mrkurt"><img src="https://avatars1.githubusercontent.com/u/7724?v=4" title="mrkurt" width="80" height="80"></a>
<a href="https://github.com/J0"><img src="https://avatars0.githubusercontent.com/u/8011761?v=4" title="J0" width="80" height="80"></a>
<a href="https://github.com/manuelfcreis"><img src="https://avatars1.githubusercontent.com/u/29898180?v=4" title="manuelfcreis" width="80" height="80"></a>
<a href="https://github.com/rberrelleza"><img src="https://avatars0.githubusercontent.com/u/475313?v=4" title="rberrelleza" width="80" height="80"></a>
<a href="https://github.com/SanketDG"><img src="https://avatars3.githubusercontent.com/u/8980971?v=4" title="SanketDG" width="80" height="80"></a>
<a href="https://github.com/sanketsaurav"><img src="https://avatars2.githubusercontent.com/u/881122?v=4" title="sanketsaurav" width="80" height="80"></a>
<a href="https://github.com/14MR"><img src="https://avatars1.githubusercontent.com/u/5824170?v=4" title="14MR" width="80" height="80"></a>
<a href="https://github.com/anandvenkat4"><img src="https://avatars2.githubusercontent.com/u/3582757?v=4" title="anandvenkat4" width="80" height="80"></a>
