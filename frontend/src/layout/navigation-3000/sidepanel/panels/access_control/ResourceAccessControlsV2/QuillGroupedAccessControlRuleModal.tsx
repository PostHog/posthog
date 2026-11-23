import { useActions, useValues } from 'kea'

import { IconHome, IconInfo } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Heading,
    Separator,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'
import { toSentenceCase } from 'lib/utils/strings'

import { AccessControlLevel } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import { groupedAccessControlRuleModalLogic } from './groupedAccessControlRuleModalLogic'
import { QuillAddLevelMenu } from './QuillAddLevelMenu'
import { QuillLevelSelect, QuillLevelSelectOption } from './QuillLevelSelect'
import { ScopeIcon } from './ScopeIcon'
import { GroupedAccessControlRuleModalLogicProps } from './types'

type ResourceLevelOption = { value: AccessControlLevel | null; label: string; disabledReason?: string }

function levelOptionsOnly(options: ResourceLevelOption[]): QuillLevelSelectOption<AccessControlLevel>[] {
    return options.filter((option): option is QuillLevelSelectOption<AccessControlLevel> => option.value !== null)
}

export function QuillGroupedAccessControlRuleModal(props: {
    state: GroupedAccessControlRuleModalLogicProps
}): JSX.Element {
    const logic = groupedAccessControlRuleModalLogic(props.state)
    const {
        modalTitle,
        loading,
        canEdit,
        terraformDisabledReason,
        formProjectLevel,
        formResourceLevels,
        projectDisabledReason,
        projectInheritedReasonTooltip,
        projectLevelOptions,
        productsDisabledReason,
        isResourceLevelShowingInherited,
        resourceInheritedReasonTooltip,
        resourceLevelOptions,
        showResourceAddOverrideButton,
    } = useValues(logic)
    const { save, close, setProjectLevel, setResourceLevel, clearResourceOverrides } = useActions(logic)
    const { resourceKeys } = useValues(accessControlsLogic({ projectId: props.state.projectId }))

    return (
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open && !loading) {
                    close()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{modalTitle}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                                <span className="flex items-center text-muted-foreground">
                                    <IconHome />
                                </span>
                                <Text size="xs" weight="medium" render={<span />}>
                                    Project access
                                </Text>
                            </div>
                            <QuillLevelSelect
                                aria-label="Project access"
                                value={formProjectLevel}
                                options={projectLevelOptions}
                                onChange={setProjectLevel}
                                disabledReason={projectDisabledReason}
                                tooltip={projectInheritedReasonTooltip}
                                className="w-36"
                            />
                        </div>

                        <Separator />

                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Products
                                </Heading>
                                <Button
                                    variant="link"
                                    size="sm"
                                    disabledReason={loading ? 'Loading...' : productsDisabledReason}
                                    onClick={clearResourceOverrides}
                                >
                                    Clear all
                                </Button>
                            </div>

                            {resourceKeys.map((resource) => {
                                const tooltipText = getAccessControlTooltip(resource.key)
                                const options = resourceLevelOptions(resource.key, resource.label)
                                return (
                                    <div
                                        key={resource.key}
                                        className="flex flex-wrap items-center justify-between gap-2"
                                    >
                                        <div className="flex items-center gap-2">
                                            <span className="flex items-center text-muted-foreground">
                                                <ScopeIcon scope={resource.key} />
                                            </span>
                                            <Text size="xs" weight="medium" render={<span />}>
                                                {resource.label}
                                            </Text>
                                            {tooltipText && (
                                                <Tooltip>
                                                    <TooltipTrigger
                                                        render={
                                                            <span className="flex items-center text-muted-foreground" />
                                                        }
                                                    >
                                                        <IconInfo />
                                                    </TooltipTrigger>
                                                    <TooltipContent>{tooltipText}</TooltipContent>
                                                </Tooltip>
                                            )}
                                        </div>
                                        {showResourceAddOverrideButton(resource.key) ? (
                                            <QuillAddLevelMenu
                                                label="Add override"
                                                options={levelOptionsOnly(options)}
                                                onSelect={(level) => setResourceLevel(resource.key, level)}
                                                disabledReason={productsDisabledReason}
                                            />
                                        ) : (
                                            <QuillLevelSelect
                                                aria-label={`${resource.label} access`}
                                                value={formResourceLevels[resource.key]}
                                                options={levelOptionsOnly(options)}
                                                allowNoOverride={options.some((option) => option.value === null)}
                                                onChange={(level) => setResourceLevel(resource.key, level)}
                                                disabledReason={productsDisabledReason}
                                                tooltip={resourceInheritedReasonTooltip(resource.key)}
                                                renderValue={(level) =>
                                                    isResourceLevelShowingInherited(resource.key)
                                                        ? toSentenceCase(level)
                                                        : (options.find((option) => option.value === level)?.label ??
                                                          '')
                                                }
                                                className="w-36"
                                            />
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close} disabledReason={loading ? 'Cannot close' : undefined}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        disabledReason={!canEdit ? (terraformDisabledReason ?? 'You cannot edit this rule') : undefined}
                        loading={loading}
                        onClick={save}
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
