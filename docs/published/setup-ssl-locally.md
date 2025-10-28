---
title: Setting up SSL locally
sidebar: Handbook
showTitle: true
---

Setting up HTTPS locally can be useful if you're trying to debug hard
to replicate issues (e.g cross domain cookies, etc).

There are two ways you can get HTTPS locally: 

1. ngrok 
2. NGINX and a local certificate. 

The easiest option is to use ngrok.

## Set up SSL via ngrok

1. Make sure you [have ngrok installed](https://ngrok.com/download).

2. Sign up for an ngrok account (or sign in with GitHub) and run `ngrok authtoken <TOKEN>`

3. Edit `$HOME/.ngrok2/ngrok.yml` and add the following after the line with `authtoken: <TOKEN>`:

```
tunnels:
  django:
    proto: http
    addr: 8000
  webpack:
    proto: http
    addr: 8234
```

4. Start ngrok. This will give you tunnel URLs such as https://68f83839843a.ngrok.io

```bash
ngrok start --all
```

5. Copy the HTTPS URL for the tunnel to port 8234 and set it as the value for the `JS_URL` environment variable. Then, start webpack:

```bash
export WEBPACK_HOT_RELOAD_HOST=0.0.0.0
export LOCAL_HTTPS=1
export JS_URL=https://68f83839843a.ngrok.io
pnpm start
```

6. Use the same URL as the value for `JS_URL` again and start the Django server

```bash
export DEBUG=1
export LOCAL_HTTPS=1
export JS_URL=https://68f83839843a.ngrok.io
python manage.py runserver
```

7. Open the HTTPS URL for the tunnel to port 8000.

**Tips & Tricks**

If you're testing the Toolbar, make sure to add the ngrok urls to the list on the 'Project Settings' page.

![Permitted domains](https://res.cloudinary.com/dmukukwp6/image/upload/v1710055416/posthog.com/contents/images/engineering/toolbar-permitted-ngrok.png)

Also, watch out, network requests can be slow through ngrok:

![Network slow with ngrok](https://res.cloudinary.com/dmukukwp6/image/upload/v1710055416/posthog.com/contents/images/engineering/ngrok-slow.gif)

## Set up SSL via NGINX and a local certificate

0. Update openssl if "openssl version" tells you "LibreSSL" or something like that.

In case `brew install openssl` and `brew link openssl` don't work well, use 
`/usr/local/opt/openssl/bin/openssl` instead of `openssl` in the next step.

1. Create key
```
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout localhost.key -out localhost.crt -subj "/CN=secure.posthog.dev" \
  -addext "subjectAltName=DNS:secure.posthog.dev,IP:10.0.0.1"
```
2. Trust the key for Chrome/Safari
```
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain localhost.crt
```
3. Add `secure.posthog.dev` to /etc/hosts
```
127.0.0.1 secure.posthog.dev
```
4. Install nginx (`brew install nginx`) and add the following config in `/usr/local/etc/nginx/nginx.conf`
```nginx
     upstream backend {
         server 127.0.0.1:8000;
     }
     server {
         server_name secure.posthog.dev;
         rewrite ^(.*) https://secure.posthog.dev$1 permanent;
     }
 
     server {
         listen       443 ssl;
         server_name  secure.posthog.dev;
         ssl_certificate  /Users/timglaser/dev/localhost.crt;
         ssl_certificate_key /Users/timglaser/dev/localhost.key    ;
         ssl_prefer_server_ciphers  on;
         ssl_session_cache    shared:SSL:1m;
         ssl_session_timeout  5m;
         ssl_ciphers          HIGH:!aNULL:!MD5;
         location / {
            proxy_pass http://backend;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Host $http_host;
            proxy_redirect off;
            proxy_set_header X-Forwarded-Proto $scheme;
         }
         location /static/ {
            proxy_pass http://127.0.0.1:8234/static/;
        }
     }
```

5. Add the following command to start nginx
```bash
nginx -p /usr/local/etc/nginx/ -c /usr/local/etc/nginx/nginx.conf
```

6. You can stop the nginx server with
```bash
nginx -p /usr/local/etc/nginx/ -c /usr/local/etc/nginx/nginx.conf -s stop
```

7. To run local development, use
```bash
bin/start-http
```
