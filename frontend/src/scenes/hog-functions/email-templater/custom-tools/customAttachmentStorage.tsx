export const unsubscribeLinkToolCustomJs = `
unlayer.registerCallback('image', function (file, done) {
  var data = new FormData();
  data.append('file', file.attachments[0]);

  fetch('/uploads', {
    method: 'POST',
    headers: {
      Accept: 'application/json',
    },
    body: data,
  })
    .then((response) => {
      // Make sure the response was valid
      if (response.status >= 200 && response.status < 300) {
        return response;
      } else {
        var error = new Error(response.statusText);
        error.response = response;
        throw error;
      }
    })
    .then((response) => {
      return response.json();
    })
    .then((data) => {
      // Pass the URL back to Unlayer to mark this upload as completed
      done({ progress: 100, url: data.filelink });
    });
});
`
