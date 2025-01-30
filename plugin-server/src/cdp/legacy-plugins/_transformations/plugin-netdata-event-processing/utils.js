export function cleanPropertyName(k) {
    return k
        // convert to lower case
        .toLowerCase()
        // remove leading slash
        .replace(/^\//, "")
        // replace all slashes and dots with _
        .replace(/\/|\.|-| /g, "_")
        ;
}

export function isStringDDMMYYYYHHMM(dt){
    var reDate = /^((0?[1-9]|[12][0-9]|3[01])[- /.](0?[1-9]|1[012])[- /.](19|20)?[0-9]{2}[ ][012][0-9][:][0-9]{2})*$/;
    return reDate.test(dt);
}

export function isDemo(url) {
    if (
        (url.includes('://london.my-netdata.io'))
        ||
        (url.includes('://london3.my-netdata.io'))
        ||
        (url.includes('://cdn77.my-netdata.io'))
        ||
        (url.includes('://octopuscs.my-netdata.io'))
        ||
        (url.includes('://bangalore.my-netdata.io'))
        ||
        (url.includes('://frankfurt.my-netdata.io'))
        ||
        (url.includes('://newyork.my-netdata.io'))
        ||
        (url.includes('://sanfrancisco.my-netdata.io'))
        ||
        (url.includes('://singapore.my-netdata.io'))
        ||
        (url.includes('://toronto.my-netdata.io'))
        ){
        return true
    } else {
        return false
    }
}

export function splitPathName(event) {
    if (event.properties['$pathname']) {
        event.properties["$pathname"].split("/").forEach((pathname, index) => {
          if ((pathname !== "") && (pathname !== null)){
            event.properties[`pathname_${index}`] = pathname
          }
        })
      }
    return event
}