import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCheckbox, IconEllipsis, IconFilter, IconFolderPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { useTreeFilterMenuItems } from '../../ProjectTree/useTreeFilterMenuItems'
import { FILES_TREE_KEY } from './navFilesTabLogic'

export function NavFilesMenu(): JSX.Element {
    const logic = projectTreeLogic({ key: FILES_TREE_KEY, root: 'project://' })
    const { selectMode, searchTerm } = useValues(logic)
    const { setSelectMode, createFolder } = useActions(logic)
    const { pendingLoaderLoading } = useValues(projectTreeDataLogic)
    const filterItems = useTreeFilterMenuItems({ key: FILES_TREE_KEY, root: 'project://' })

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    items: [
                        {
                            label: selectMode === 'default' ? 'Enable multi-select' : 'Disable multi-select',
                            icon: <IconCheckbox />,
                            active: selectMode === 'multi',
                            'data-attr': 'tree-panel-enable-multi-select-button',
                            onClick: () => {
                                posthog.capture('project tree multi-select toggled', {
                                    root: 'project://',
                                    enabled: selectMode === 'default',
                                })
                                setSelectMode(selectMode === 'default' ? 'multi' : 'default')
                            },
                        },
                    ],
                },
                {
                    items: [
                        {
                            label: 'Filters',
                            icon: <IconFilter />,
                            active: !!searchTerm.trim(),
                            items: filterItems.flatMap((section) => section.items),
                            closeOnClickInside: false,
                            closeParentPopoverOnClickInside: false,
                            'data-attr': 'tree-filters-dropdown-menu-trigger-button',
                        },
                    ],
                },
                {
                    items: [
                        {
                            label: 'New root folder',
                            icon: <IconFolderPlus />,
                            'data-attr': 'tree-panel-new-root-folder-button',
                            disabledReason: pendingLoaderLoading ? 'Saving changes...' : undefined,
                            onClick: () => createFolder(''),
                        },
                    ],
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                tooltip="Files options"
                aria-label="Files options"
                data-attr="tree-panel-options-button"
                active={!!searchTerm.trim() || selectMode === 'multi'}
            />
        </LemonMenu>
    )
}
