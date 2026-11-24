import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Skeleton } from '@posthog/quill'

import { isProjectGroupTag } from 'lib/components/Account/projectGroupTags'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useRestrictedArea, RestrictionScope } from 'lib/components/RestrictedArea'
import { useTagSourceExcluding } from 'lib/components/useTagPages'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { projectTagsLogic } from './projectTagsLogic'
import { QuillProjectTags } from './QuillProjectTags'

export function ProjectTags(): JSX.Element {
    const {
        currentProject,
        currentProjectLoading,
        regularTags,
        canEditProjectGroup,
        projectGroup,
        projectGroupTagChanged,
        projectGroupOptions,
        projectGroupValidationErrors,
        projectGroupHasErrors,
        isProjectGroupSubmitting,
    } = useValues(projectTagsLogic)
    const { updateTags, setProjectGroupValue } = useActions(projectTagsLogic)
    const regularTagSource = useTagSourceExcluding(isProjectGroupTag)

    // Regular project tags use project access; the API also restricts group changes to organization admins.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentProject) {
        return todayRailNav ? <Skeleton className="w-40 h-5" /> : <LemonSkeleton className="w-40 h-5" />
    }

    if (restrictionReason) {
        return <ObjectTags tags={regularTags} staticOnly data-attr="project-tags" />
    }

    if (todayRailNav) {
        return <QuillProjectTags regularTagSource={regularTagSource} />
    }

    return (
        <div className="flex flex-col gap-3">
            <ObjectTags
                tags={regularTags}
                loadTags={regularTagSource}
                onChange={updateTags}
                saving={currentProjectLoading}
                data-attr="project-tags"
            />
            {canEditProjectGroup && (
                <Form logic={projectTagsLogic} formKey="projectGroup" enableFormOnSubmit className="max-w-80">
                    <LemonField.Pure label="Project group" error={projectGroupValidationErrors.name}>
                        <div className="flex gap-1">
                            <LemonInputSelect
                                className="flex-1"
                                mode="single"
                                allowCustomValues
                                disabled={currentProjectLoading || isProjectGroupSubmitting}
                                value={projectGroup.name ? [projectGroup.name] : []}
                                onChange={(values) => setProjectGroupValue('name', values[0] ?? '')}
                                options={projectGroupOptions}
                                inputTransform={(input) => input.slice(0, 200)}
                                placeholder="For example, production apps"
                                data-attr="project-group-input"
                            />
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                disabled={!projectGroupTagChanged || projectGroupHasErrors}
                                loading={currentProjectLoading || isProjectGroupSubmitting}
                                data-attr="project-group-save"
                            >
                                Save
                            </LemonButton>
                        </div>
                    </LemonField.Pure>
                </Form>
            )}
        </div>
    )
}
