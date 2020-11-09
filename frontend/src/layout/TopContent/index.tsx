import React from 'react'
import { LatestVersion } from './LatestVersion'
import { Projects, User } from './TopSelectors'
import { CommandPaletteButton } from './CommandPaletteButton'
import { isMobile } from 'lib/utils'
import './index.scss'
import { Link } from 'lib/components/Link'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { topContentLogic } from './topContentLogic'
import { useValues } from 'kea'

export function TopContent(): JSX.Element {
    const { backTo } = useValues(topContentLogic)

    return (
        <div className="main-app-content layout-top-content" style={{ paddingTop: 16 }}>
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
                    <Link to={backTo?.url}>
                        <ArrowLeftOutlined /> Back to {backTo?.display}
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
                <Projects />
                <User />
            </div>
        </div>
    )
}
