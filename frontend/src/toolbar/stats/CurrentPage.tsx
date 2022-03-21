import './CurrentPage.scss'
import React, { useState } from 'react'
import { useValues } from 'kea'
import { GlobalOutlined } from '@ant-design/icons'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { Comment } from 'antd'

function getFavicon(): string {
    let favicon
    const nodeList = document.getElementsByTagName('link')
    for (let i = 0; i < nodeList.length; i++) {
        if (nodeList[i].getAttribute('rel') === 'icon' || nodeList[i].getAttribute('rel') === 'shortcut icon') {
            favicon = nodeList[i].getAttribute('href')
        }
    }
    return favicon || '/favicon.ico'
}

// make the url word-wrap at every "/"
function addWBRToUrl(url: string): JSX.Element {
    return (
        <>
            {url.split('/').map((part, index) => (
                <React.Fragment key={index}>
                    {index === 0 ? '' : '/'}
                    <wbr />
                    {part}
                </React.Fragment>
            ))}
        </>
    )
}

export function CurrentPage(): JSX.Element {
    const { href } = useValues(currentPageLogic)
    const [showIcon, setShowIcon] = useState(true)

    return (
        <div className="current-page">
            <Comment
                avatar={
                    showIcon ? (
                        <img
                            src={getFavicon()}
                            onError={() => setShowIcon(false)}
                            width={32}
                            height={32}
                            alt="FavIcon"
                        />
                    ) : (
                        <GlobalOutlined />
                    )
                }
                content={
                    <div>
                        <div>{window.document.title}</div>
                        <div className="small-url-link">
                            <a href={href} target="_blank" rel="noreferrer noopener">
                                {addWBRToUrl(href)}
                            </a>
                        </div>
                    </div>
                }
            />
        </div>
    )
}
