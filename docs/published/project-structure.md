---
title: Project structure
sidebar: Docs
showTitle: true
---

> **Note:** This page refers to our [main product repository](https://github.com/PostHog/posthog), not our website.

## Directory tree 

```
.
├── .github
├── .platform
├── bin
├── cypress
├── ee  
├── frontend
│   └── public
│   └── src
│       └── layout
│       └── lib
│       └── models
│       └── scenes
│       └── style
│       └── toolbar
├── livestream
├── posthog
│   └── api
│   └── management
│   └── migrations
│   └── models
│   └── queries
│   └── tasks
│   └── templates
│   └── test
└── requirements

*Selected subdirectories only

```

## `.github`

Directory for our GitHub actions and templates for issues and pull requests.

## `.platform`

Scripts for deploying to Platform.sh.

## `bin`

Executable shell scripts for various purposes, most notably building, testing, and running PostHog.

## `cypress`

Hosts our [Cypress](https://www.cypress.io/) tests. When writing tests that use Cypress, you will mostly be working on the `integration/` subdirectory. Remember that you should always be including tests if you are making a significant change to our frontend.

## `ee`

Enterprise Edition features for PostHog. This subdirectory is the only subdirectory not MIT-Licensed in the [PostHog/posthog](https://github.com/PostHog/posthog) repository, and a license is needed to use its features. To use PostHog with 100% FOSS code, refer to our [PostHog/posthog-foss](https://github.com/PostHog/posthog-foss) repository.

## `frontend`

Hosts the PostHog frontend, built with React.

### Subdirectories

#### `public`

PostHog logos to be used by the app.

#### `src`

Code for the frontend.

##### `src/layout`

Components referring to the overall PostHog app layout, such as sections of the app used in most pages, like `Sidebar.js`.

##### `src/lib`

Various components used all around the PostHog app. Reusable components will most likely be placed in this subdirectory, such as buttons, charts, etc.

##### `src/models`

[Kea](https://github.com/keajs/kea) models for the app's state. 

##### `src/scenes`

Components referring to specific pages of the PostHog app. Mostly non-reusable. 

##### `src/styles`

[Sass](https://sass-lang.com/) files for the PostHog app's style.

##### `toolbar`

All code related exclusively to the [PostHog Toolbar](/docs/user-guides/toolbar).

## `livestream`

The live events API, a Golang service (used in the Live tab of Activity in the app).

## `posthog`

Hosts the PostHog backend, built with Django.

### Subdirectories

#### `api`

Subdirectory for PostHog's REST API. Includes its own tests.

#### `management`

Custom [Django management commands](https://docs.djangoproject.com/en/3.1/howto/custom-management-commands/). Commands defined here are registered as `manage.py` commands and can be called with:

```bash
./manage.py <your_command_here>
# or
python manage.py <your_command_here>
```

These commands are for admin use only, and generally refer to the configuration of your Django app.

#### `migrations`

Hosts the database migrations which occur when there are changes to the models. If you make any changes to the app's ORM, you need to first make migrations: 
```
python manage.py makemigrations
```

And after making your own migrations or running `git pull` after new migrations, you also need to apply them:
```
python manage.py migrate
```

#### `ClickHouse Migrations`

To create boilerplate for clickhouse migrations use 
```
python manage.py create_ch_migration --name <name of migration>
```

To apply clickhouse migrations use
```
python manage.py migrate_clickhouse
```

#### `models`

Subdirectory for the models ([Django ORM](https://docs.djangoproject.com/en/3.1/topics/db/models/)). Interactions with our database are handled by these models. 

#### `queries`

Hosts the queries used to query data from our database, which will be used by our various features, such as [Retention](/docs/user-guides/retention) and [Trends](/docs/user-guides/trends). 

#### `tasks`

Celery tasks that happen in the "background" of the server to enhance PostHog's performance by preventing long processes from  blocking the main thread. An example of task is processing events as they come in. 

#### `templates`

[Django templates](https://docs.djangoproject.com/en/3.1/topics/templates/) used to generate dynamic HTML. We use templates for pages such as `/login` and `/setup_admin`. 

#### `test`

Subdirectory hosting our backend tests. You should always include tests when you make changes to our backend. 

### `requirements`

Hosts our backend's dev requirements. 
