import React from 'react'
import { Link } from './Link'
import { ArrowLeftOutlined } from '@ant-design/icons'

import { kea, useValues } from 'kea'
import { backToLogicType } from './BackToType'

interface BackTo {
    display: string
    url: string
}

const backToLogic = kea<backToLogicType>({
    actions: {
        setBackTo: (payload) => ({ payload }),
    },

    reducers: {
        backTo: [
            null as BackTo | null,
            {
                setBackTo: (_, { payload }) => payload,
            },
        ],
    },
    urlToAction: ({ actions }) => ({
        '*': ({}, {}, { backTo, backToURL }: { backTo: string | null; backToURL: string | null }) => {
            if (!backTo || !backToURL) {
                actions.setBackTo(null)
            } else {
                actions.setBackTo({ display: backTo, url: backToURL })
            }
        },
    }),
})

export function BackTo(): JSX.Element {
    const { backTo } = useValues(backToLogic)
    return (
        <>
            {backTo && (
                <div className="mt-2">
                    <Link to={backTo?.url}>
                        <ArrowLeftOutlined /> Back to {backTo?.display}
                    </Link>
                </div>
            )}
        </>
    )
}
