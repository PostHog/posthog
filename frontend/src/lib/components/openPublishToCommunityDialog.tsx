import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

export interface PublishToCommunityOptions {
    display_name?: string
    tags?: string[]
    author_handle?: string
}

/** Collect the public listing fields, then give them to the product that owns the publish action. */
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
    LemonDialog.openForm({
        title: 'Publish to community',
        description: isScout
            ? "Publishing commits the scout's instructions, schedule, inbox setting, and tags to a public GitHub repository. It then opens a pull request. The contents are public when you submit them. Do not include credentials or internal details."
            : "Publishing commits the skill's instructions, bundled files, and template variables to a public GitHub repository. It then opens a pull request. The contents are public when you submit them. Do not include credentials or internal details.",
        initialValues: {
            display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase()),
            tags: '',
            author_handle: githubLogin ?? '',
        },
        content: (
            <div className="flex flex-col gap-2">
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
        onSubmit: ({ display_name, tags, author_handle }) =>
            onPublish(skillName, {
                display_name: display_name?.trim() || undefined,
                tags: tags
                    ? tags
                          .split(',')
                          .map((tag: string) => tag.trim())
                          .filter(Boolean)
                    : undefined,
                author_handle: author_handle?.trim() || undefined,
            }),
    })
}
