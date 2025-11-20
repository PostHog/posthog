import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { notificationsLogic } from 'lib/logic/notificationsLogic'
import { userLogic } from 'scenes/userLogic'

export function useNotificationsWebSocket(): { connected: boolean } {
    const { user } = useValues(userLogic)
    const [connected, setConnected] = useState(false)
    const wsRef = useRef<WebSocket | null>(null)
    const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
    const reconnectAttemptsRef = useRef(0)

    useEffect(() => {
        if (!user) {
            return
        }

        const connect = (): void => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
            const tokenParam = user.personal_api_key ? `?token=${user.personal_api_key}` : ''
            // Use the same host as the current page for WebSocket connection
            const wsUrl = `${protocol}//${window.location.host}/ws/notifications/${tokenParam}`

            try {
                const ws = new WebSocket(wsUrl)
                wsRef.current = ws

                ws.onopen = () => {
                    setConnected(true)
                    reconnectAttemptsRef.current = 0
                    notificationsLogic.findMounted()?.actions.setWebSocketConnected(true)
                }

                ws.onmessage = (event) => {
                    try {
                        const notification = JSON.parse(event.data)
                        // The backend sends the notification object directly, not wrapped
                        if (notification && notification.id) {
                            notificationsLogic.findMounted()?.actions.addNotification(notification)
                        }
                    } catch (error) {
                        console.error('[Notifications WebSocket] Error parsing message:', error)
                    }
                }

                ws.onerror = (error) => {
                    console.error('[Notifications WebSocket] Error:', error)
                }

                ws.onclose = () => {
                    setConnected(false)
                    notificationsLogic.findMounted()?.actions.setWebSocketConnected(false)
                    wsRef.current = null

                    // Exponential backoff reconnection
                    const backoffMs = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000)

                    reconnectTimeoutRef.current = setTimeout(() => {
                        reconnectAttemptsRef.current++
                        connect()
                    }, backoffMs)
                }
            } catch (error) {
                console.error('[Notifications WebSocket] Connection error:', error)
            }
        }
        connect()

        // Cleanup function
        return () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current)
            }
            if (wsRef.current) {
                wsRef.current.close()
                wsRef.current = null
            }
        }
    }, [user])

    return { connected }
}
