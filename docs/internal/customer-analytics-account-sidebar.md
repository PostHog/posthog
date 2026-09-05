# Account detail sidebar properties

Each user can pin up to 50 account custom properties and relationships in their project.
The Pin properties button and the Properties gear open the same ordered selector.
Dragging entries changes their saved display order. The sidebar scrolls independently of
the main account content on wide account scenes.

Pinned rows load current values for the selected account. Missing custom values display
"Not set" and relationships without current assignees display "Unassigned". Loading and
failed requests have separate states, with retry available after a failure.

Account editors can edit manual and workflow-backed properties inline. Workflow-backed
rows warn that a workflow may overwrite a manual change. Warehouse-backed and canonical
properties are read-only. Date and datetime pickers provide their own apply and cancel
controls; other editors use Clear value, Cancel, and Save.

Clearing a custom value requires confirmation and posts a null value to
`POST /api/projects/:project_id/accounts/:account_id/custom_property_values/`.
The endpoint returns 204, soft-deletes the current value, and preserves its history.
Warehouse-backed values reject both manual sets and clears.

Relationship editors support single and multiple holders. Removing a holder ends the
assignment without deleting its history. Multi-holder changes retain unchanged holders.
Clearing every holder requires confirmation. Failed saves keep the editor open; after a
partial relationship failure, the sidebar reloads current assignments so a retry uses
the latest state.

Pin preferences belong to `accountSidebarConfigLogic`, keyed by project. Live values and
editing state belong to `accountSidebarPropertiesLogic`, keyed by project and account.
The Relationships tab and account list refresh after assignment changes.
