export const unsubscribeLinkToolCustomJs = `

unlayer.registerTool({
    name: 'unsubscribe_link',
    label: 'Unsubscribe',
    icon: 'fa-hand-pointer',
    supportedDisplayModes: ['email'],
    options: {
        unsubscribe_link: {
            // Property Group
            title: 'Unsubscribe link content', // Title for Property Group
            position: 1, // Position of Property Group
            collapsed: false, // Initial collapse state
            options: {
                unsubscribe_link_content: {
                    // Property: textColor
                    label: 'content', // Label for Property
                    defaultValue: \`<div>Don't want to receive these emails? <a href="{{ unsubscribe_link }}">Unsubscribe</a></div>\`,
                    widget: 'rich_text', // Property Editor Widget: color_picker
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
})`
