export const listMyFlagsAPIResponse = [
    {
        feature_flag: {
            id: 15927,
            name: 'Example flag',
            key: 'example-one',
            deleted: false,
            active: true,
            created_at: '2023-08-17T19:37:05.259538Z',
            filters: {},
        },
        value: false,
    },
    {
        feature_flag: {
            id: 15927,
            name: 'Another example flag',
            key: 'example-two',
            deleted: false,
            active: true,
            created_at: '2023-08-17T19:37:05.259538Z',
            filters: {},
        },
        value: true,
    },
    {
        feature_flag: {
            id: 13859,
            name: 'Example multivariate flag',
            key: 'my-multi-example',
            filters: {
                multivariate: {
                    variants: [
                        {
                            key: 'control',
                            rollout_percentage: 50,
                        },
                        {
                            key: 'test',
                            rollout_percentage: 50,
                        },
                    ],
                },
            },
            deleted: false,
            active: true,
        },
        value: 'control',
    },
    {
        feature_flag: {
            id: 13859,
            name: 'Example overridden multivariate flag',
            key: 'my-other-multi-example',
            filters: {
                multivariate: {
                    variants: [
                        {
                            key: 'control',
                            rollout_percentage: 50,
                        },
                        {
                            key: 'test',
                            rollout_percentage: 50,
                        },
                    ],
                },
            },
            deleted: false,
            active: true,
        },
        value: 'control',
    },
]
