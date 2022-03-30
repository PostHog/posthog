const aws = require('aws-sdk')

const s3 = new aws.S3({
    endpoint: 'http://localhost:19000',
    accessKeyId: 'object_storage_root_user',
    secretAccessKey: 'object_storage_root_password',
    s3ForcePathStyle: true, // needed with minio?
    signatureVersion: 'v4',
})

// // putObject operation.

// let params = {Bucket: 'posthog', Key: 'testobject', Body: 'Hello from MinIO!!'};

// s3.putObject(params, function(err, data) {
//       if (err)
//        console.log(err)
//       else
//        console.log("Successfully uploaded data to testbucket/testobject");
// });

// // getObject operation.

// var params = {Bucket: 'testbucket', Key: 'testobject'};

// var file = require('fs').createWriteStream('/tmp/mykey');

// s3.getObject(params).
// on('httpData', function(chunk) { file.write(chunk); }).
// on('httpDone', function() { file.end(); }).
// send();
