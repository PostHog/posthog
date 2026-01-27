import { IconCursorClick, IconPencil } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function NewActionButton({ onSelectOption }: { onSelectOption?: () => void }): JSX.Element {
    return (
        <AccessControlAction resourceType={AccessControlResourceType.Action} minAccessLevel={AccessControlLevel.Editor}>
            <AppShortcut
                name="NewAction"
                keybind={[keyBinds.new]}
                intent="New action"
                interaction="click"
                scope={Scene.Actions}
            >
                <LemonButton
                    type="primary"
                    size="small"
                    to={urls.createAction()}
                    onClick={onSelectOption}
                    data-attr="create-action"
                    tooltip="New action"
                    sideAction={{
                        dropdown: {
                            placement: 'bottom-end',
                            className: 'w-80',
                            overlay: (
                                <div className="space-y-1 p-1">
                                    <LemonButton
                                        fullWidth
                                        icon={<IconPencil />}
                                        to={urls.createAction()}
                                        onClick={onSelectOption}
                                        data-attr="new-action-pageview"
                                    >
                                        <div className="flex flex-col items-start">
                                            <span>From event or pageview</span>
                                            <span className="text-xs text-secondary font-normal">
                                                Match events by name, URL patterns, or custom properties.{' '}
                                                <Link
                                                    to="https://posthog.com/docs/data/actions"
                                                    target="_blank"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    Learn more
                                                </Link>
                                            </span>
                                        </div>
                                    </LemonButton>
                                    <LemonButton
                                        fullWidth
                                        icon={<IconCursorClick />}
                                        to={urls.toolbarLaunch()}
                                        data-attr="new-action-inspect"
                                    >
                                        <div className="flex flex-col items-start">
                                            <span>Inspect element on site</span>
                                            <span className="text-xs text-secondary font-normal">
                                                Use the toolbar to visually select elements on your site.{' '}
                                                <Link
                                                    to="https://posthog.com/docs/toolbar/create-toolbar-actions"
                                                    target="_blank"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    Learn more
                                                </Link>
                                            </span>
                                        </div>
                                    </LemonButton>
                                </div>
                            ),
                        },
                    }}
                >
                    New action
                </LemonButton>
            </AppShortcut>
        </AccessControlAction>
    )
}
