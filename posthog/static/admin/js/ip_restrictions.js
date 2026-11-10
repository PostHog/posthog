document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-add-ip-restriction], [data-remove-ip-restriction]')
    if (!button) {
        return
    }
    const widget = button.closest('[data-ip-restrictions-widget]')
    const tbody = widget.querySelector('tbody')
    if (button.hasAttribute('data-add-ip-restriction')) {
        const row = widget.querySelector('template').content.cloneNode(true)
        tbody.appendChild(row)
        tbody.lastElementChild.querySelector('input').focus()
    } else {
        button.closest('tr').remove()
        if (!tbody.children.length) {
            tbody.appendChild(widget.querySelector('template').content.cloneNode(true))
        }
    }
})
