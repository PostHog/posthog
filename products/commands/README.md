# Commands

People with write access to a repository can ask PostHog to do something on a pull request by commenting a command on it:

```text
@posthog review
@posthog review --deep
@posthog stamp
@posthog qa the signup form
@posthog loop Triage PR
@posthog help
```

Each command dispatches into the product that owns the work.
This product owns the parsing, the checks and the replies, and owns no work of its own.

A command comes in through a channel and acts on a subject.
The channels are GitHub pull request comments and Slack mentions.
The subjects are pull requests and, from Slack, PostHog error tracking issues.

[`COMMANDS.generated.md`](COMMANDS.generated.md) lists every command, and [`commands.generated.json`](commands.generated.json) is the same reference for tools.
Both are generated from `backend/logic/schema.py`, like the `@posthog help` reply.

## Grammar

- A command is a line that starts with `@posthog`, then the command name.
- Options come next. A flag is `--name`, such as `--deep`. An option with a value is `--name value` or `--name=value`. Names are lowercase, with no short forms.
- Option reading stops at the first word that does not start with `--`. Everything from there to the end of the line is the command's text, kept as typed, such as the focus in `@posthog qa the signup form`. A command has at most one text field.
- A lone `--` also stops option reading, so the text can start with `--`: `@posthog qa -- --verbose flags`.
- Quotes and apostrophes are plain text. Nothing splits the text like a shell does.
- Some commands have another name. `@posthog approve` runs `stamp`. Replies and help use the main name.
- An unknown option, an option given twice, a missing value, a value that is not allowed, text for a command that takes none, or missing required text runs nothing. The reply shows the correct usage.

## How a comment becomes a command

1. `backend/webhook_consumers.py` registers the `commands` consumer for `issue_comment` on the customer-facing GitHub App endpoint.
2. `channels/github/intake.py` reads the payload inside the webhook request, with no database and no API call. It drops everything that is not a new command comment and queues a task for the rest. `channels/github/parsing.py` finds the command: the CommonMark reference parser gives the comment's block structure, and a command fires only from a top-level paragraph.
3. `channels/github/comments.py` runs in the task. It applies the comment's silent checks (listed in its module docstring), then hands the command to `logic/dispatcher.py`, which runs the steps every channel shares and calls the command's handler.
4. `logic/handlers.py` calls the target product's facade and returns the text of the reply.

## Commands from Slack

The same commands run from a Slack message that mentions the PostHog app and names the subject by its URL, before or after the command.
A pull request is named by its GitHub URL, and an error tracking issue by its URL in this PostHog instance:

```text
@PostHog review --deep https://github.com/PostHog/posthog/pull/123
@PostHog https://github.com/PostHog/posthog/pull/123 review --deep
@PostHog qa https://github.com/PostHog/posthog/pull/123 check the signup form
@PostHog resolve https://us.posthog.com/project/2/error_tracking/01890a5d-ac96-774b-b3f2-3e3c8a6d2b11
@PostHog https://us.posthog.com/project/2/error_tracking/01890a5d-ac96-774b-b3f2-3e3c8a6d2b11 assign
```

- Only a message that opens with the app's mention and reads exactly as a command runs one. Free text, such as "can you review this deeply", and a mistyped option go to the agent as before.
- The `slack-commands` flag decides the rollout per organization, once, inside the Slack webhook. Outside it, the message also goes to the agent.
- Every command that ran gets an answer in the thread, refusals included, because the message no longer reaches the agent.
- When the work a command started ends, its result follows in the same thread: the review's findings count, Stamphog's outcome, or the end of the QA run. A pull request comment needs no follow-up, because the work posts its result on the pull request.
- The Slack app asks `may_hold_command` first, a check with no queries, so most mentions never reach this product. It hands the rest to `accept_slack_mention` inside its webhook, as plain text. This product reads it (`channels/slack/`), runs it in its own task like a pull request comment, and answers in the thread through the Slack integration the mention came in on.
- A Slack command has no GitHub permission check. It runs as a PostHog account that is a member of the project, like the review trigger in the PostHog API and MCP.
- It may run as the accounts the Slack app resolves for the person, the ones its agent acts as: first their linked PostHog account, else the member of a connected organization with their Slack email, then every other account linked to their Slack user. The command picks the project first, and the first of these accounts that is a member of it acts there.
- It reaches only projects of organizations that connected that Slack workspace, the same scope the agent has. In a shared channel that has not approved PostHog, the message goes to the agent, whose approval gate applies.

## Subjects

The subject is the thing a command acts on, such as a pull request.
A channel names it with a reference: a comment names the pull request it sits on, and a Slack message names a pull request or an error tracking issue by its URL.
`logic/subjects.py` owns everything that depends on the kind of subject:

- The candidate projects a command may run in, before the rollout. For a pull request, the projects whose GitHub integration uses the installation.
- How to reach the subject, such as a GitHub client for a pull request.
- The facts a handler gets, and the refusals before it runs, such as a closed pull request or a fork.

For an error tracking issue, the URL names the issue by id, or by fingerprint as error tracking's Slack alerts link it, and the fingerprint resolves to whichever issue owns it now.
The project is the one in the URL, and only a URL of this instance counts, because project ids repeat across regions.
Its reply never repeats the issue's name, because the name comes from captured exception text that people outside the organization can write.

The dispatcher, the identity step and the access step only use the subject through that module.
Each command declares the kinds it accepts in `subject_kinds`, and dispatch answers when a request names another kind.

To add a kind of subject:

1. Add its reference and facts types to `logic/commands.py`.
2. Add a class that follows `Subject`, and a case in each function, in `logic/subjects.py`.
3. Teach the channels that can name it to read it, for example a URL pattern in `channels/slack/parsing.py`.
4. Add the kind to `subject_kinds` of the commands that accept it.

## Results that come later

The first answer says that the work started.
A channel that wants the result later gives an address (`follow_up` on the channel), and the handler saves it with `logic/follow_ups.py` before the work ends.
The products report the end without importing this product: Stamphog and PostHog Review call the callbacks registered in their `facade/finished_review_hooks.py`, and a QA run's terminal save fires the task run signal.
`receivers.py` registers all three at app start, builds the message in `logic/results.py`, and queues it.
A follow-up record lives in the cache for a day, so a lost record loses only the follow-up message.

## Adding a command

Declare the command in `logic/schema.py`: an args dataclass built with `flag()`, `option()` and `text()`, and a `CommandDeclaration` in `COMMAND_DECLARATIONS`.
Set `subject_kinds` to the kinds of subject the command acts on. The default is pull requests only.
Set `access` when the target product has a resource in PostHog access control, at the level its own API asks for the same action.
Leave `allows_forks` off unless the command reads nothing from the pull request head.
Write a handler in `logic/handlers.py` that takes the args dataclass and calls the target product's facade, then bind the two in `logic/registry.py`.
Run `hogli build:projections` and commit the regenerated command reference.

A product that wants a command does not need Loops, and does not need to know about GitHub comments or Slack.
It needs a facade function that takes a project, a user and the subject's identifiers.

## Trust model

A command runs as the commenter's own PostHog user, in a project they are a member of.
So a command can only do what the commenter could already do in PostHog, and a comment gives nobody access they did not have.

The checks that make that true:

- **Who is asking.** The webhook's `author_association` filters out outside contributors before a task is queued. The task then asks GitHub for the commenter's permission on the repository and requires write access, for the commenter's numeric account id, so a login that changed hands does not count.
- **Which PostHog user.** The match is on GitHub's numeric user id, never on the login, and only through identities GitHub confirmed to PostHog: a connected GitHub account or GitHub login. A GitHub account can be linked to several PostHog accounts, for example a work and a personal one. The command picks the project first, and the linked account that is a member of it acts there. When two linked accounts are members of that project, the one linked most recently acts.
- **Which project.** Only projects whose GitHub integration uses the installation the comment came from, that the user is a member of, and that are in the `github-commands` rollout. For an environment, the user must also be a member of its parent project. An organization that enforces verified email domains gives no project to a user whose email is outside them, as the product APIs do. `review` runs only in the project that owns the repository in PostHog Review, and the commenter must be a member of it.
- **Which product gates.** A command applies the gates the target product's own API applies. `loop` needs Loops access, and `qa` needs PostHog Code access for the commenter's organization and PostHog Code credits left.
- **What the person typed.** Only a new comment counts, so an edit cannot turn a reviewed comment into a command. Comments by bots, and comments a GitHub App posted with a person's token, never run a command. That covers PostHog's own replies and coding agents that act as a user.
- **One run per comment.** Ingress dedups the delivery, and dispatch claims the comment id. If the claim cannot be written, the command does not run, so a redelivery cannot start a second paid run. When GitHub cannot answer the permission lookup, dispatch releases the claim, because nothing ran.
- **Cost.** Each commenter has a rate limit, checked before any GitHub call. A commenter over the limit gets no reaction and no reply.

## Prompt injection

Several commands start an agent, and a pull request is full of text other people wrote.
The defenses do not depend on an agent ignoring instructions:

- The parser reads only lines that start with the mention, and only in top-level paragraphs as the CommonMark reference parser reads them.
  Text that GitHub shows as a quote, code, a list item, a table or an HTML block never counts, and neither do inline code, images, inline HTML with the text after it, or a paragraph with a table row, so text that shows or repeats a command does not run it.
  A comment longer than 10,000 characters is ignored, because a command comment is short.
- The command's argument is the commenter's own words, cleaned of control and invisible characters and capped in length. It is treated as their instruction, because the run uses their access.
- Handlers pass identifiers, never the pull request title, body or other comments. The product reads that content itself and treats it as untrusted.
- A command runs only when the pull request's branch name is a plain identifier: letters, digits, `.`, `_`, `/` and `-`. Even then, the name never goes into a prompt or a loop payload. Only the head commit SHA does, and the QA task gets the branch as checkout data.
- Fork pull requests are refused by every command that runs or reviews code.
- The QA task gets the head commit seen at request time, and is told to stop if the branch moved since.
- A loop fires only for its owner, because a loop runs with its owner's credentials and its payload becomes part of its prompt.
- Replies are built from fixed text and values PostHog or GitHub produced. A reply never repeats what the comment said, so nobody can make the bot post their text.
- People without write access get no reply, so the bot is no oracle and no amplifier for them.

## Not built yet

- `@posthog fix`: a PostHog Code task that pushes to the pull request branch. It needs Tasks to support committing to an existing pull request head.
- Commands in review threads (`pull_request_review_comment`), which the GitHub App is not subscribed to yet.
- Commands on issues.
