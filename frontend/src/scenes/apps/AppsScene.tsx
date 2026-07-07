import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import {
    getDefaultTreeDataAndPeople,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { HomeViewToggle } from '~/layout/scenes/HomeViewToggle'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

export const scene: SceneExport = {
    component: AppsScene,
}

function getItemName(item: FileSystemImport): string {
    return item.displayLabel ?? unescapePath(splitPath(item.path).pop() ?? item.path)
}

function getAppItems(featureFlags: Record<string, boolean | string | undefined>): FileSystemImport[] {
    const seen = new Set<string>()
    return [...getDefaultTreeProducts(), ...getDefaultTreeDataAndPeople()]
        .filter((item) => !!item.href && (!item.flag || !!featureFlags[item.flag]))
        .filter((item) => {
            const name = getItemName(item)
            if (seen.has(name)) {
                return false
            }
            seen.add(name)
            return true
        })
        .sort((a, b) => getItemName(a).localeCompare(getItemName(b), undefined, { sensitivity: 'accent' }))
}

export function AppsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const items = getAppItems(featureFlags)

    return (
        <div className="relative h-full overflow-y-auto">
            <HomeViewToggle current="apps" />
            <div className="max-w-[1280px] mx-auto px-8 pt-14 pb-8 group/colorful-product-icons colorful-product-icons-true">
                <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
                    {items.map((item) => (
                        <Link
                            key={getItemName(item)}
                            to={item.href}
                            className="flex flex-col items-center justify-center gap-2 rounded-lg border p-4 bg-surface-primary hover:bg-surface-secondary text-primary hover:text-primary"
                            data-attr="apps-grid-item"
                        >
                            <span className="text-2xl [&_svg]:size-8">
                                {iconForType(
                                    (item.iconType ?? (item.type as FileSystemIconType)) || undefined,
                                    item.iconColor
                                )}
                            </span>
                            <span className="text-sm font-medium text-center">
                                {getItemName(item)}
                                {item.tags?.map((tag) => (
                                    <LemonTag
                                        key={tag}
                                        size="small"
                                        type={tag === 'alpha' ? 'completion' : 'warning'}
                                        className="ml-1 uppercase"
                                    >
                                        {tag}
                                    </LemonTag>
                                ))}
                            </span>
                        </Link>
                    ))}
                </div>
            </div>
        </div>
    )
}
