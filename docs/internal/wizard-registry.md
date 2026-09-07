# Wizard registry

Status: design document for the Wizard run stack.
This layer ships only the data models and the registry parsing described under "Remote configuration".
The "API" routes and the "Cloud execution" workers describe planned behavior and do not exist yet; they land in later stack layers.

The Wizard Registry lists the programs a person can run in the Wizard.
Programs are personalized by the signed-in user's distinct ID and the organization that owns the selected project.

## API

The registry endpoint returns a paginated list:

```text
GET /api/projects/{project_id}/wizard/registry/?limit=100&offset=0
```

Each program contains an ID, display metadata, a pinned Wizard version, Wizard command arguments, tags, prerequisite program IDs, and supported run environments.

Creating a run requires the selected `program_id`:

```json
{
  "program_id": "posthog-integration",
  "environment": "local",
  "workspace": {
    "type": "local_folder",
    "project_name": "example-project"
  }
}
```

The backend resolves the ID from the personalized registry, checks that the program supports the requested environment, and stores the complete program definition on the run.
Clients cannot supply or change program metadata.
Run responses return the stored `program` snapshot.

## Remote configuration

The registry is stored in the `wizard-program-registry` feature flag payload:

```json
{
  "version": 1,
  "programs": [
    {
      "id": "web-analytics-audit",
      "name": "Web analytics audit",
      "description": "Audit a project's web analytics setup",
      "wizard_version": "2.60.0",
      "command": ["audit", "web-analytics"],
      "tags": ["audit", "web-analytics"],
      "required_programs": ["posthog-integration"],
      "supported_environments": ["local", "cloud"]
    }
  ]
}
```

The entire payload is invalid when its version or shape is unsupported, program IDs are duplicated, an environment is unknown, or any program field is invalid.
Each program must include a `wizard_version` pinned to an exact release, such as `2.60.0`.
The registry payload rejects `latest`, so a program that omits `wizard_version` or sets it to `latest` makes the whole payload invalid.
A valid empty program list remains empty.

When the payload cannot be fetched or is invalid, the registry contains one `posthog-integration` program with local and cloud support.
Its command is empty, which keeps the Wizard package's default command.

## Cloud execution

Cloud workers execute the program snapshot stored when the run was created.
They do not evaluate the registry again.
They run the pinned `wizard_version` from that snapshot, never a mutable tag such as `latest`.

Program command tokens are positional command names.
They appear after `@posthog/wizard@{program.wizard_version}` and before worker-owned flags.
Option flags and shell syntax are rejected, and every accepted token is shell-quoted before execution.
