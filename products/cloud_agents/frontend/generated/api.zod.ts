/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * A preset is a named set of run defaults. A run that names a preset needs only a prompt.
 * @summary Create a preset
 */
export const cloudAgentsPresetsCreateBodyRepositoriesItemNameMax = 255

export const cloudAgentsPresetsCreateBodyRepositoriesItemNameRegExp = new RegExp('^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$')
export const cloudAgentsPresetsCreateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsPresetsCreateBodyModelMax = 100

export const cloudAgentsPresetsCreateBodyInstructionsMax = 20000

export const cloudAgentsPresetsCreateBodyIdleMinutesMax = 120

export const cloudAgentsPresetsCreateBodyDescriptionMax = 2000

export const cloudAgentsPresetsCreateBodyTagsItemMax = 50

export const cloudAgentsPresetsCreateBodyTagsMax = 20

export const cloudAgentsPresetsCreateBodyNameMax = 100

export const CloudAgentsPresetsCreateBody = /* @__PURE__ */ zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsPresetsCreateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsPresetsCreateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsPresetsCreateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsPresetsCreateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        description: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyDescriptionMax)
            .optional()
            .describe('What this preset is for.'),
        tags: zod
            .array(zod.string().max(cloudAgentsPresetsCreateBodyTagsItemMax))
            .max(cloudAgentsPresetsCreateBodyTagsMax)
            .optional()
            .describe('Tags added to every run that uses this preset.'),
        name: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyNameMax)
            .describe('Name of the preset. It is unique in the project, without regard to case.'),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')

/**
 * Only the fields in the request change. A null value clears a default.
 * @summary Update a preset
 */
export const cloudAgentsPresetsPartialUpdateBodyRepositoriesItemNameMax = 255

export const cloudAgentsPresetsPartialUpdateBodyRepositoriesItemNameRegExp = new RegExp(
    '^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$'
)
export const cloudAgentsPresetsPartialUpdateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsPresetsPartialUpdateBodyModelMax = 100

export const cloudAgentsPresetsPartialUpdateBodyInstructionsMax = 20000

export const cloudAgentsPresetsPartialUpdateBodyIdleMinutesMax = 120

export const cloudAgentsPresetsPartialUpdateBodyDescriptionMax = 2000

export const cloudAgentsPresetsPartialUpdateBodyTagsItemMax = 50

export const cloudAgentsPresetsPartialUpdateBodyTagsMax = 20

export const cloudAgentsPresetsPartialUpdateBodyNameMax = 100

export const CloudAgentsPresetsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsPresetsPartialUpdateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsPresetsPartialUpdateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsPresetsPartialUpdateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsPresetsPartialUpdateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsPresetsPartialUpdateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsPresetsPartialUpdateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        description: zod
            .string()
            .max(cloudAgentsPresetsPartialUpdateBodyDescriptionMax)
            .optional()
            .describe('What this preset is for.'),
        tags: zod
            .array(zod.string().max(cloudAgentsPresetsPartialUpdateBodyTagsItemMax))
            .max(cloudAgentsPresetsPartialUpdateBodyTagsMax)
            .optional()
            .describe('Tags added to every run that uses this preset.'),
        name: zod
            .string()
            .max(cloudAgentsPresetsPartialUpdateBodyNameMax)
            .optional()
            .describe('Name of the preset. It is unique in the project, without regard to case.'),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')

/**
 * Starts a sandbox with a coding agent that works on the prompt in the repository. The response returns at once with a `queued` run. Read the run or stream its events to follow it. Send the same `Idempotency-Key` header again to get the same run and not a second one.
 * @summary Start a run
 */
export const cloudAgentsRunsCreateBodyRepositoriesItemNameMax = 255

export const cloudAgentsRunsCreateBodyRepositoriesItemNameRegExp = new RegExp('^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$')
export const cloudAgentsRunsCreateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsRunsCreateBodyModelMax = 100

export const cloudAgentsRunsCreateBodyInstructionsMax = 20000

export const cloudAgentsRunsCreateBodyIdleMinutesMax = 120

export const cloudAgentsRunsCreateBodyPromptMax = 64000

export const cloudAgentsRunsCreateBodyPresetMax = 100

export const cloudAgentsRunsCreateBodyTagsItemMax = 50

export const cloudAgentsRunsCreateBodyTagsMax = 20

export const cloudAgentsRunsCreateBodyMetadataMaxOne = 512

export const CloudAgentsRunsCreateBody = /* @__PURE__ */ zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsRunsCreateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsRunsCreateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsRunsCreateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'The repositories that the agent works in. Only one repository is supported for now. Required unless the preset or the project settings set a default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsRunsCreateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsRunsCreateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsRunsCreateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        prompt: zod
            .string()
            .max(cloudAgentsRunsCreateBodyPromptMax)
            .describe('The task for the agent, in plain language.'),
        preset: zod
            .string()
            .max(cloudAgentsRunsCreateBodyPresetMax)
            .nullish()
            .describe(
                'ID or name of the preset whose defaults the run uses. Null uses the default preset of the project, when one is set.'
            ),
        tags: zod
            .array(zod.string().max(cloudAgentsRunsCreateBodyTagsItemMax))
            .max(cloudAgentsRunsCreateBodyTagsMax)
            .optional()
            .describe('Tags for the run. The tags of the preset are added to them.'),
        metadata: zod
            .record(zod.string(), zod.string().max(cloudAgentsRunsCreateBodyMetadataMaxOne))
            .optional()
            .describe(
                'Your own key and value pairs, stored with the run and returned with it. At most 16 pairs. Keys and values are strings.'
            ),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')

/**
 * Sends a follow-up message. An agent that is at work gets the message in its current session. An `idle` run starts a new agent session with the message and goes back to `queued`. A `done` run refuses the message with status 409 and the code `run_done`.
 * @summary Send a message to a run
 */
export const cloudAgentsRunsMessagesCreateBodyContentMax = 64000

export const CloudAgentsRunsMessagesCreateBody = /* @__PURE__ */ zod.object({
    content: zod
        .string()
        .max(cloudAgentsRunsMessagesCreateBodyContentMax)
        .describe('The follow-up message for the agent, in plain language.'),
})

/**
 * Only the fields in the request change. A null value clears a default.
 * @summary Update cloud agent settings
 */
export const cloudAgentsSettingsPartialUpdateBodyRepositoriesItemNameMax = 255

export const cloudAgentsSettingsPartialUpdateBodyRepositoriesItemNameRegExp = new RegExp(
    '^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$'
)
export const cloudAgentsSettingsPartialUpdateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsSettingsPartialUpdateBodyModelMax = 100

export const cloudAgentsSettingsPartialUpdateBodyInstructionsMax = 20000

export const cloudAgentsSettingsPartialUpdateBodyIdleMinutesMax = 120

export const CloudAgentsSettingsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsSettingsPartialUpdateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsSettingsPartialUpdateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsSettingsPartialUpdateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsSettingsPartialUpdateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsSettingsPartialUpdateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsSettingsPartialUpdateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        default_preset: zod
            .uuid()
            .nullish()
            .describe('ID of the preset that a run uses when it names no preset. Null sets no default preset.'),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')
