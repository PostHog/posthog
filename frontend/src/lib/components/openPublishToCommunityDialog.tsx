import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { PublishToCommunityContents } from 'products/skills/frontend/PublishToCommunityContents'

export interface PublishToCommunityOptions {
    expected_skill_id: string
    expected_version: number
    display_name?: string
    tags?: string[]
    author_handle?: string
}

/** Collect the publish fields, then hand them to `onPublish`. Shared so the list view and the
 * single-skill view open the identical dialog. */
export function openPublishToCommunityDialog({
    skillName,
    githubLogin,
    isScout,
    onPublish,
}: {
    skillName: string
    githubLogin: string | null
    isScout?: boolean
    onPublish: (skillName: string, options: PublishToCommunityOptions) => void
}): void {
    let expectedSkill: { id: string; version: number } | null = null

    LemonDialog.openForm({
        title: 'Publish to the PostHog community?',
        description: isScout
            ? "Publishing commits the scout's instructions, schedule, inbox setting, and tags to a public GitHub repository. It then opens a pull request. The contents are public when you submit them. Do not include credentials or internal details."
            : 'If approved for the PostHog catalog, all PostHog users can find and use this skill. Its contents will be public on GitHub immediately.',
        initialValues: {
            display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            tags: '',
            // Prefill with the user's resolved GitHub handle when we have one; the field stays
            // editable so users without a linked GitHub identity can still type one (free-text fallback).
            author_handle: githubLogin ?? '',
            consent: false,
        },
        content: (
            <div className="flex flex-col gap-2">
                <PublishToCommunityContents
                    skillName={skillName}
                    onPreviewChange={(preview) => {
                        expectedSkill = preview ? { id: preview.id, version: preview.version } : null
                    }}
                />
                <LemonField name="display_name" label="Display name">
                    <LemonInput data-attr="llma-publish-display-name" autoFocus />
                </LemonField>
                <LemonField name="tags" label="Tags (comma-separated)">
                    <LemonInput data-attr="llma-publish-tags" placeholder="web-analytics, triage" />
                </LemonField>
                <LemonField name="author_handle" label="Your GitHub handle (optional)">
                    <LemonInput data-attr="llma-publish-author-handle" placeholder="octocat" />
                </LemonField>
            </div>
        ),
        errors: {
            consent: (consent: boolean) =>
                consent ? undefined : 'Review the skill and confirm that you can share it publicly',
        },
        primaryButtonProps: { children: 'Publish to community' },
        onSubmit: ({ display_name, tags, author_handle }) => {
            if (expectedSkill === null) {
                return
            }
            onPublish(skillName, {
                expected_skill_id: expectedSkill.id,
                expected_version: expectedSkill.version,
                display_name: display_name?.trim() || undefined,
                tags: tags
                    ? tags
                          .split(',')
                          .map((t: string) => t.trim())
                          .filter(Boolean)
                    : undefined,
                author_handle: author_handle?.trim() || undefined,
            })
        },
    })
}
