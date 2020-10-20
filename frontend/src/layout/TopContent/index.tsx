import React, { useEffect, useState } from 'react'
import { LatestVersion } from './LatestVersion'
import { User } from './User'
import { CommandPaletteButton } from './CommandPaletteButton'
import { isMobile } from 'lib/utils'
import { router } from 'kea-router'
import './index.scss'
import { Link } from 'lib/components/Link'
import { ArrowLeftOutlined } from '@ant-design/icons'

export function TopContent(): JSX.Element {
    const [{ backTo, backToURL }, setHashParams] = useState(router.values.hashParams)
    useEffect(() => {
        setHashParams(router.values.hashParams)
    }, [router.values.hashParams])

    return (
        <div className="content py-3 layout-top-content">
            <div
                className="layout-top-content"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                {backTo ? (
                    <Link to={backToURL}>
                        <ArrowLeftOutlined /> Back to {backTo}
                    </Link>
                ) : (
                    !isMobile() && <CommandPaletteButton />
                )}
            </div>
            <div
                className="layout-top-content"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                <LatestVersion />
                <User />
            </div>
        </div>
    )
}
