import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { TimestampFormat, playerSettingsLogic } from '../player/playerSettingsLogic'

export function useHideRecordingsMenuItems(): LemonMenuItem[] {
    const { hideViewedRecordings, hideRecordingsMenuLabelFor } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const items: LemonMenuItem[] = [
        {
            label: hideRecordingsMenuLabelFor(false),
            onClick: () => setHideViewedRecordings(false),
            active: !hideViewedRecordings,
            'data-attr': 'hide-viewed-recordings-show-all',
        },
        {
            label: hideRecordingsMenuLabelFor('current-user'),
            onClick: () => setHideViewedRecordings('current-user'),
            active: hideViewedRecordings === 'current-user',
            'data-attr': 'hide-viewed-recordings-hide-current-user',
        },
    ]

    if (!featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]) {
        items.push({
            label: hideRecordingsMenuLabelFor('any-user'),
            onClick: () => setHideViewedRecordings('any-user'),
            active: hideViewedRecordings === 'any-user',
            'data-attr': 'hide-viewed-recordings-hide-any-user',
        })
    }

    return items
}

export function useTimestampFormatMenuItems(): LemonMenuItem[] {
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setPlaylistTimestampFormat } = useActions(playerSettingsLogic)

    return [TimestampFormat.UTC, TimestampFormat.Device, TimestampFormat.Relative].map((format) => ({
        label: TimestampFormatToLabel[format],
        onClick: () => setPlaylistTimestampFormat(format),
        active: playlistTimestampFormat === format,
        'data-attr': `filters-timestamp-${String(format).toLowerCase()}`,
    }))
}

export function useAutoplayMenuItems(): LemonMenuItem[] {
    const { autoplayDirection } = useValues(playerSettingsLogic)
    const { setAutoplayDirection } = useActions(playerSettingsLogic)

    return [
        {
            label: 'Off',
            onClick: () => setAutoplayDirection(null),
            active: !autoplayDirection,
            'data-attr': 'list-autoplay-off',
        },
        {
            label: 'Newer recordings',
            onClick: () => setAutoplayDirection('newer'),
            active: autoplayDirection === 'newer',
            'data-attr': 'list-autoplay-newer',
        },
        {
            label: 'Older recordings',
            onClick: () => setAutoplayDirection('older'),
            active: autoplayDirection === 'older',
            'data-attr': 'list-autoplay-older',
        },
    ]
}
