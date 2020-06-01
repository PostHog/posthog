import React, { useState, useEffect } from 'react'
import { useActions, useValues } from 'kea'

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
    const { setHref } = useActions(currentPageLogic)
    const [showIcon, setShowIcon] = useState(true)

    useEffect(() => {
        const interval = window.setInterval(() => {
            if (window.location.href !== href) {
                setHref(window.location.href)
            }
        }, 500)
        return () => window.clearInterval(interval)
    }, [href])

    useEffect(() => {
        const locationListener = () => {
            setHref(window.location.href)
        }
        window.addEventListener('popstate', locationListener)
        return () => {
            window.removeEventListener('popstate', locationListener)
        }
    }, [])

    return (
        <div className="float-box">
            <div style={{ display: 'flex', alignItems: 'top' }}>
                {showIcon ? (
                    <div style={{ width: 46, minWidth: 46 }}>
                        <img
                            src={getFavicon()}
                            onError={() => setShowIcon(false)}
                            width={32}
                            height={32}
                            alt="FavIcon"
                        />
                    </div>
                ) : null}
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
