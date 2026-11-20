import { Text } from '@posthog/quill'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { UserBasicType } from '~/types'

import { TZLabel } from '../TZLabel'

export function QuillUserActivityIndicator({
    at,
    by,
    prefix = 'Last modified',
}: {
    prefix?: string
    at: string | null | undefined
    by?: UserBasicType | null | undefined
}): JSX.Element | null {
    return at || by ? (
        <Text size="xs" variant="muted" render={<div className="m-0 flex flex-wrap items-center gap-1" />}>
            <span>{prefix}</span>
            {at && <TZLabel time={at} />}
            {by && <span>by</span>}
            {by && <ProfilePicture user={by} showName size="md" />}
        </Text>
    ) : null
}
