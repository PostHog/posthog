import { useValues } from 'kea'

import { LemonBadge, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { parentPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { fileSystemTypes } from '~/products'

import { SceneTitleSameNameLogicProps, sceneTitleSameNameLogic } from './sceneTitleSameNameLogic'

export function SceneTitleSameNameBadge(props: SceneTitleSameNameLogicProps): JSX.Element | null {
    const { sameNameItems } = useValues(sceneTitleSameNameLogic(props))

    if (sameNameItems.length === 0) {
        return null
    }

    const typeName = Object.hasOwn(fileSystemTypes, props.type)
        ? fileSystemTypes[props.type as keyof typeof fileSystemTypes].name.toLowerCase()
        : 'item'
    const message = `This shares the same name as ${pluralize(sameNameItems.length, `other ${typeName}`)}, remember to change the name to something meaningful`

    return (
        <Tooltip
            interactive
            placement="bottom-start"
            title={
                <div className="flex flex-col gap-2 max-w-80">
                    <span>{message}</span>
                    <ul className="flex flex-col gap-1">
                        {sameNameItems.map((entry) => (
                            <li key={entry.id} className="flex flex-col min-w-0">
                                <Link to={entry.href} className="truncate" data-attr="scene-title-same-name-link">
                                    {splitPath(entry.path).pop()}
                                </Link>
                                <span className="text-xs opacity-75 truncate">
                                    {[
                                        splitPath(parentPath(entry.path)).join(' / '),
                                        entry.created_at ? `created ${dayjs(entry.created_at).fromNow()}` : null,
                                    ]
                                        .filter(Boolean)
                                        .join(' · ')}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            }
        >
            <span className="flex self-start shrink-0 cursor-help" data-attr="scene-title-same-name-badge">
                <LemonBadge content="!" status="muted" size="small" />
            </span>
        </Tooltip>
    )
}
