import { useMemo } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { ActionMenu, Button } from '@posthog/quill'

import { captureSceneMenuBar } from '../components/captureSceneMenuBar'
import { SceneAction, SceneActionGroup, buildSceneActionMenu, stripSceneFields } from './sceneActionModel'

// pinned: data-attr and analytics property values are wire strings
export const SCENE_ACTIONS_TRIGGER_DATA_ATTR = 'scene-menu-bar-trigger'
const LAYOUT = 'scene-actions'
const TRIGGER_LABEL = 'More actions'

interface SceneActionMenuProps {
    actions: SceneAction[]
    dataAttrKey?: string
    menuDataAttrs?: Partial<Record<SceneActionGroup, string>>
    /** Help-only menus are short, so they skip the search field. */
    helpOnly?: boolean
}

export function SceneActionMenu({
    actions,
    dataAttrKey,
    menuDataAttrs,
    helpOnly = false,
}: SceneActionMenuProps): JSX.Element {
    // A help-only menu is the Help rows themselves, with no Help submenu to open first.
    const items = useMemo(
        () => (helpOnly ? actions.map(stripSceneFields) : buildSceneActionMenu(actions, dataAttrKey, menuDataAttrs)),
        [actions, dataAttrKey, menuDataAttrs, helpOnly]
    )
    const captureProperties = helpOnly ? { layout: LAYOUT, help_only: true } : { layout: LAYOUT }

    return (
        <div data-attr="scene-menu-bar" className="scene-menu-bar flex items-center">
            <ActionMenu
                items={items}
                searchable={!helpOnly}
                trigger={
                    <Button
                        size="icon"
                        aria-label={TRIGGER_LABEL}
                        tooltip={TRIGGER_LABEL}
                        data-attr={SCENE_ACTIONS_TRIGGER_DATA_ATTR}
                    />
                }
                triggerChildren={<IconEllipsis />}
                onOpenChange={(open) => {
                    if (open) {
                        captureSceneMenuBar('scene menu bar menu opened', { menu: null, ...captureProperties })
                    }
                }}
                onSubmenuOpenChange={(item, open) => {
                    if (open) {
                        captureSceneMenuBar('scene menu bar menu opened', { menu: item.label, ...captureProperties })
                    }
                }}
                onSearch={() => captureSceneMenuBar('scene menu bar searched', captureProperties)}
                onItemSelect={(item, { fromSearch }) => {
                    if (item.type !== 'submenu') {
                        captureSceneMenuBar('scene menu bar item clicked', {
                            item: item.dataAttr ?? item.id,
                            ...captureProperties,
                            from_search_results: fromSearch,
                        })
                    }
                }}
            />
        </div>
    )
}
