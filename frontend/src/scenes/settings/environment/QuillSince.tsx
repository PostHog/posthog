import { ComponentProps } from 'react'

import { IconCheck, IconInfo } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { isObject } from 'lib/utils/guards'

import { Since } from './SessionRecordingSettings'

export function QuillSince(props: ComponentProps<typeof Since>): JSX.Element {
    const platforms = Object.entries(props).filter(([_, value]) => !!value)

    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="Supported SDK versions" />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent>
                <ul className="m-0 flex flex-col gap-1 p-0">
                    {platforms.map(([key, value]) => (
                        <li key={key} className="flex flex-row justify-between gap-x-2">
                            <span>{key}:</span>
                            {isObject(value) && !!value.version ? <span>since {value.version}</span> : <IconCheck />}
                        </li>
                    ))}
                </ul>
            </TooltipContent>
        </Tooltip>
    )
}
