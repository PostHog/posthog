export const listExperimentsAPIResponse = {
    results: [
        {
            id: 3,
            name: 'Page Header Test',
            feature_flag_key: 'signup-button-test',
            variants: [
                {
                    transforms: [
                        {
                            html: "Its Corinne's birthday",
                            text: 'International Space Station\n',
                            selector: '#page > #body > .body h1',
                        },
                    ],
                    variant_name: 'Signup',
                    rollout_percentage: 25,
                },
                {
                    transforms: [
                        {
                            html: 'One giant leap for Omega Watches',
                            text: "Neil Armstrong's Party Pad",
                            selector: '#page > #body > .body h1',
                        },
                    ],
                    variant_name: 'Send-it',
                    rollout_percentage: 25,
                },
                {
                    transforms: [
                        {
                            html: 'I am the control',
                            text: 'Cosmonaut Happy Hour',
                            selector: '#page > #body > .body h1',
                        },
                    ],
                    variant_name: 'control',
                    rollout_percentage: 50,
                },
            ],
        },
        {
            id: 2,
            name: 'HomePage hero banner test',
            feature_flag_key: 'amazon-hero-text',
            variants: [
                {
                    transforms: [
                        {
                            html: '',
                            text: 'Ola Amigo',
                            selector: '#page > #body > .body h1',
                            className: 'O',
                        },
                    ],
                    variant_name: 'variant #0',
                    rollout_percentage: 50,
                },
                {
                    transforms: [
                        {
                            html: '',
                            text: 'Hello world',
                            selector: '#page > #body > .body h1',
                        },
                    ],
                    variant_name: 'variant #1',
                    rollout_percentage: 50,
                },
            ],
        },
    ],
}
