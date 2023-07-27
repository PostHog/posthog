/* This file sets theming configuration on Ant Design for PostHog.
When changing any variable here, please remember to update vars.scss too  */

import { ThemeConfig } from 'antd'

export default {
    token: {
        borderRadius: 4,
        colorTextSecondary: '#403939',
        colorPrimary: '#1d4aff',
        colorLink: '#1d4aff',
        colorSuccess: '#388600',
        colorWarning: '#f7a501',
        colorError: '#db3707',
        colorTextDisabled: '#5f5f5f',
        colorText: '#2d2d2d',
        colorBorder: 'rgba(0, 0, 0, 0.15)',
        colorTextHeading: '#2d2d2d',
    },
    components: {
        App: {
            colorText: '#2d2d2d',
            fontFamily:
                "-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol'",
            fontSize: 14,
        },
        Layout: {
            colorBgBody: '#fff',
        },
    },
} as ThemeConfig
