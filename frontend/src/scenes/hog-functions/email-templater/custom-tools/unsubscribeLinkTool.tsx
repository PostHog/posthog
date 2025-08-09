export const unsubscribeLinkToolCustomJs = `
unlayer.registerTool({ 
    name: 'unsubscribe_link',
    label: 'Unsubscribe',
    icon: 'fa-hand-pointer',
    supportedDisplayModes: ['email'],
    position: 15,
    options: {
        unsubscribe_link: {
            // Property Group
            title: 'Unsubscribe link content', 
            position: 1, 
            collapsed: false,
            options: {
                unsubscribe_link_content: {
                    label: 'Content',
                    defaultValue: \`<div>Don't want to receive these emails? <a href="{{ unsubscribe_url }}">Unsubscribe</a></div>\`,
                    widget: 'rich_text',
                },
            },
        },
    },
    values: {},
    renderer: {
        Viewer: unlayer.createViewer({
            render(values) {
                return \`\${values.unsubscribe_link_content}\`
            },
        }),
        exporters: {
            email: function (values) {
                return \`\${values.unsubscribe_link_content}\`
            },
        },
    },
})
`
