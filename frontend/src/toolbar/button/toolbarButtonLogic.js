import { kea } from 'kea'

export const toolbarButtonLogic = kea({
    actions: () => ({
        setExtensionPercentage: percentage => ({ percentage }),
        setQuarter: quarter => ({ quarter }),
    }),

    reducers: () => ({
        extensionPercentage: [
            0,
            {
                setExtensionPercentage: (_, { percentage }) => percentage,
            },
        ],
        quarter: [
            'ne',
            {
                setQuarter: (_, { quarter }) => quarter,
            },
        ],
    }),
})
