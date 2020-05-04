import { Link } from 'react-router-dom'
import React from 'react'

export function NoItems() {
    return (
        <tr>
            <td colSpan={4}>
                You don't have any items here. If you haven't integrated PostHog yet,{' '}
                <Link to="/setup">click here to set PostHog up on your app</Link>
            </td>
        </tr>
    )
}
