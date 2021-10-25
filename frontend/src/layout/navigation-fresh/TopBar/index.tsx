import { useValues } from 'kea'
import React from 'react'
import { FEATURE_FLAGS } from '../../../lib/constants'
import { featureFlagLogic } from '../../../lib/logic/featureFlagLogic'
import { FriendlyLogo } from '../../../toolbar/assets/FriendlyLogo'
import { AccountControl } from './AccountControl'
import { Announcement } from './Announcement'
import { SearchBox } from './SearchBox'
import './TopBar.scss'

export function TopBar(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            {featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT] &&
                featureFlags[FEATURE_FLAGS.LEMONADE] &&
                featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT] && (
                    <Announcement message={String(featureFlags[FEATURE_FLAGS.CLOUD_ANNOUNCEMENT])} />
                )}
            <header className="TopBar">
                <div className="TopBar__segment">
                    <FriendlyLogo />
                    <SearchBox />
                </div>
                <div className="TopBar__segment">
                    <AccountControl />
                </div>
            </header>
        </>
    )
}
