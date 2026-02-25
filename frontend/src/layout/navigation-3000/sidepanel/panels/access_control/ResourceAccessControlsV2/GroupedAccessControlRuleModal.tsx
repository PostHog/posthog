import { useActions, useValues } from 'kea'

import { IconHome, IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonModal, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { toSentenceCase } from 'lib/utils'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { accessControlsLogic } from './accessControlsLogic'
import { groupedAccessControlRuleModalLogic } from './groupedAccessControlRuleModalLogic'
import { ScopeIcon } from './ScopeIcon'
import { GroupedAccessControlRuleModalLogicProps } from './types'

export function GroupedAccessControlRuleModal(props: { state: GroupedAccessControlRuleModalLogicProps }): JSX.Element {
    const { modalTitle, loading, canEdit } = useValues(groupedAccessControlRuleModalLogic(props.state))
    const { save, close } = useActions(groupedAccessControlRuleModalLogic(props.state))

    return (
        <LemonModal
            isOpen={true}
            onClose={loading ? undefined : close}
            title={modalTitle}
            maxWidth="32rem"
            footer={
                <GroupedAccessControlRuleModalFooter close={close} loading={loading} canEdit={canEdit} onSave={save} />
            }
        >
            <GroupedAccessControlRuleModalContent logicProps={props.state} />
        </LemonModal>
    )
}

function GroupedAccessControlRuleModalFooter(props: {
    close: () => void
    loading: boolean
    canEdit: boolean
    onSave: () => void
}): JSX.Element {
    return (
        <div className="flex items-center justify-end gap-2">
            <LemonButton
                type="secondary"
                onClick={props.close}
                disabledReason={props.loading ? 'Cannot close' : undefined}
            >
                Cancel
            </LemonButton>
            <LemonButton
                type="primary"
                disabledReason={!props.canEdit ? 'You cannot edit this rule' : undefined}
                loading={props.loading}
                onClick={props.onSave}
            >
                Save
            </LemonButton>
        </div>
    )
}

function GroupedAccessControlRuleModalContent(props: {
    logicProps: GroupedAccessControlRuleModalLogicProps
}): JSX.Element {
    const { projectId } = props.logicProps
    const {
        loading,
        formProjectLevel,
        formResourceLevels,
        projectDisabledReason,
        projectInheritedReasonTooltip,
        projectLevelOptions,
        featuresDisabledReason,
        isResourceLevelShowingInherited,
        resourceInheritedReasonTooltip,
        resourceLevelOptions,
        showResourceAddOverrideButton,
    } = useValues(groupedAccessControlRuleModalLogic(props.logicProps))
    const { setProjectLevel, setResourceLevel, clearResourceOverrides } = useActions(
        groupedAccessControlRuleModalLogic(props.logicProps)
    )

    const { resourceKeys } = useValues(accessControlsLogic({ projectId }))

    return (
        <div className="space-y-4">
            <div className="flex gap-2 items-center justify-between">
                <div className="font-medium flex items-center gap-2">
                    <span className="text-lg flex items-center text-muted-alt">
                        <IconHome />
                    </span>
                    Project access
                </div>
                <div className="min-w-[8rem]">
                    <LemonSelect
                        dropdownPlacement="bottom-end"
                        value={formProjectLevel}
                        disabledReason={projectDisabledReason}
                        tooltip={projectInheritedReasonTooltip}
                        size="small"
                        className="w-36"
                        onChange={setProjectLevel}
                        options={projectLevelOptions}
                    />
                </div>
            </div>

            <LemonDivider className="mb-4" />

            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h5 className="mb-2">Features</h5>
                    <Link
                        to="#"
                        onClick={(e) => {
                            e.preventDefault()
                            if (!loading && !featuresDisabledReason) {
                                clearResourceOverrides()
                            }
                        }}
                        className={
                            loading || featuresDisabledReason
                                ? 'cursor-not-allowed opacity-50 pointer-events-none'
                                : 'cursor-pointer'
                        }
                    >
                        Clear all
                    </Link>
                </div>

                {resourceKeys.map((resource) => {
                    const tooltipText = getAccessControlTooltip(resource.key)
                    return (
                        <div key={resource.key} className="flex gap-2 items-center justify-between">
                            <div className="font-medium flex items-center gap-2">
                                <span className="text-lg flex items-center text-muted-alt">
                                    <ScopeIcon scope={resource.key} />
                                </span>
                                {resource.label}
                                {tooltipText && (
                                    <Tooltip title={tooltipText}>
                                        <IconInfo className="text-sm text-muted" />
                                    </Tooltip>
                                )}
                            </div>
                            <div className="min-w-[8rem]">
                                {showResourceAddOverrideButton(resource.key) ? (
                                    <LemonDropdown
                                        placement="bottom-end"
                                        overlay={
                                            <div className="flex flex-col">
                                                {resourceLevelOptions(resource.key, resource.label).map((option) => (
                                                    <LemonButton
                                                        key={option.value}
                                                        size="small"
                                                        className="w-36"
                                                        fullWidth
                                                        disabledReason={option.disabledReason}
                                                        onClick={() => setResourceLevel(resource.key, option.value)}
                                                    >
                                                        {option.label}
                                                    </LemonButton>
                                                ))}
                                            </div>
                                        }
                                    >
                                        <LemonButton
                                            size="small"
                                            type="tertiary"
                                            icon={<IconPlus />}
                                            sideIcon={null}
                                            disabledReason={featuresDisabledReason}
                                            className="ml-auto w-36"
                                        >
                                            Add override
                                        </LemonButton>
                                    </LemonDropdown>
                                ) : (
                                    <LemonSelect
                                        className="w-36"
                                        size="small"
                                        value={formResourceLevels[resource.key]}
                                        disabledReason={featuresDisabledReason}
                                        tooltip={resourceInheritedReasonTooltip(resource.key)}
                                        renderButtonContent={(leaf) => {
                                            const level = formResourceLevels[resource.key]
                                            if (isResourceLevelShowingInherited(resource.key) && level) {
                                                return toSentenceCase(level)
                                            }
                                            return leaf?.label ?? ''
                                        }}
                                        onChange={(value) => setResourceLevel(resource.key, value)}
                                        options={resourceLevelOptions(resource.key, resource.label)}
                                    />
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
