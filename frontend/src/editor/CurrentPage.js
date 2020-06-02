import React, { useState } from 'react'
import { useValues } from 'kea'
import { GlobalOutlined } from '@ant-design/icons'
import { currentPageLogic } from '~/editor/currentPageLogic'

function getFavicon() {
    var favicon = undefined
    var nodeList = document.getElementsByTagName('link')
    for (var i = 0; i < nodeList.length; i++) {
        if (nodeList[i].getAttribute('rel') === 'icon' || nodeList[i].getAttribute('rel') === 'shortcut icon') {
            favicon = nodeList[i].getAttribute('href')
        }
    }
    return favicon || '/favicon.ico'
}

// make the url word-wrap at every "/"
function addWBRToUrl(url) {
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

export function CurrentPage() {
    const { href } = useValues(currentPageLogic)
    const [showIcon, setShowIcon] = useState(true)

    return (
        <div className="float-box">
            <div style={{ display: 'flex', alignItems: 'top' }}>
                <div style={{ width: 46, minWidth: 46 }}>
                    {showIcon ? (
                        <img
                            src={getFavicon()}
                            onError={() => setShowIcon(false)}
                            width={32}
                            height={32}
                            alt="FavIcon"
                        />
                    ) : (
                        <GlobalOutlined style={{ fontSize: 32, color: 'hsl(240, 12%, 82%)' }} />
                    )}
                </div>
                <div
                    style={{
                        fontSize: '16px',
                        lineHeight: '20px',
                        marginTop: -4,
                        minHeight: 40,
                        display: 'flex',
                        alignItems: 'center',
                        overflow: 'hidden',
                    }}
                >
                    <div style={{ width: '100%' }}>
                        <div>{window.document.title}</div>
                        <div style={{ fontSize: 12, marginTop: 2, wordBreak: 'break-word' }}>
                            <a href={href} target="_blank" rel="noreferrer noopener" style={{ color: '#888' }}>
                                {addWBRToUrl(href)}
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
