import { useEffect, useState } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { fileSystemTypes } from '~/products'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { CustomMenuProps } from '../types'

interface ResourceMenuProps extends CustomMenuProps {
    resource: {
        type: string
        ref: string
    }
    resetPanelLayout: (animate: boolean) => void
}

export function ResourceMenuItems({
    MenuItem = DropdownMenuItem,
    resource,
    resetPanelLayout,
}: ResourceMenuProps): JSX.Element | null {
    const resourceMeta = fileSystemTypes[resource.type] ?? null

    const [object, setObject] = useState(false as Record<string, any> | false | null)
    useEffect(() => {
        if (resourceMeta && resourceMeta.fetch) {
            resourceMeta
                .fetch(resource.ref)
                .then(setObject)
                .catch(() => {
                    setObject(null)
                })
        }
    }, [resourceMeta])
    //
    // const resourceStates = resourceMeta?.states
    // const resourceActions = resourceMeta?.actions

    if (!resource.type) {
        return <></>
    }

    return (
        <>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                }}
            >
                <ButtonPrimitive menuItem>
                    <div className="flex gap-2">
                        {iconForType(resource.type as FileSystemIconType)}{' '}
                        {object ? (
                            (resourceMeta.getName?.(object) ?? 'Untitled')
                        ) : object === null ? (
                            'Error'
                        ) : (
                            <Spinner />
                        )}
                    </div>
                </ButtonPrimitive>
            </MenuItem>
            {object ? (
                <>
                    {resourceMeta?.states?.(object)?.map((state) => (
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                resetPanelLayout(false)
                            }}
                        >
                            <ButtonPrimitive menuItem>
                                {state.name}: {String(state.value)}
                            </ButtonPrimitive>
                        </MenuItem>
                    ))}
                    {resourceMeta
                        ?.actions?.(object)
                        ?.filter((a) => ('if' in a ? a.if : true))
                        .map((action) => (
                            <MenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    action.perform()
                                    resetPanelLayout(false)
                                }}
                            >
                                <ButtonPrimitive menuItem>{action.name}</ButtonPrimitive>
                            </MenuItem>
                        ))}
                </>
            ) : null}
        </>
    )
}
