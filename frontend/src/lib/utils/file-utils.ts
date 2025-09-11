export function selectFiles(options: { contentType: string; multiple: boolean }): Promise<File[]> {
    return new Promise((resolve, reject) => {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = options.multiple
        input.accept = options.contentType

        input.onchange = () => {
            if (!input.files) {
                return resolve([])
            }
            const files = Array.from(input.files)
            resolve(files)
        }

        input.oncancel = () => {
            resolve([])
        }
        input.onerror = () => {
            reject(new Error('Error selecting file'))
        }

        input.click()
    })
}

export function getTextFromFile(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const filereader = new FileReader()
        filereader.onload = (e) => {
            resolve(e.target?.result as string)
        }
        filereader.onerror = (e) => {
            reject(e)
        }
        filereader.readAsText(file)
    })
}
