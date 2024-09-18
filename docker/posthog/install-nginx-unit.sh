#!/bin/sh

set -ex &&
    savedAptMark="$(apt-mark showmanual)" &&
    apt-get update &&
    apt-get install --no-install-recommends --no-install-suggests -y ca-certificates git build-essential libssl-dev libpcre2-dev curl pkg-config &&
    mkdir -p /usr/lib/unit/modules /usr/lib/unit/debug-modules &&
    mkdir -p /usr/src/unit &&
    cd /usr/src/unit &&
    git clone --depth 1 -b 1.33.0-1 https://github.com/nginx/unit &&
    cd unit &&
    NCPU="$(getconf _NPROCESSORS_ONLN)" &&
    DEB_HOST_MULTIARCH="$(dpkg-architecture -q DEB_HOST_MULTIARCH)" &&
    CC_OPT="$(DEB_BUILD_MAINT_OPTIONS="hardening=+all,-pie" DEB_CFLAGS_MAINT_APPEND="-Wp,-D_FORTIFY_SOURCE=2 -fPIC" dpkg-buildflags --get CFLAGS)" &&
    LD_OPT="$(DEB_BUILD_MAINT_OPTIONS="hardening=+all,-pie" DEB_LDFLAGS_MAINT_APPEND="-Wl,--as-needed -pie" dpkg-buildflags --get LDFLAGS)" &&
    CONFIGURE_ARGS_MODULES="--prefix=/usr \
                --statedir=/var/lib/unit \
                --control=unix:/var/run/control.unit.sock \
                --runstatedir=/var/run \
                --pid=/var/run/unit.pid \
                --logdir=/var/log \
                --log=/var/log/unit.log \
                --tmpdir=/var/tmp \
                --user=unit \
                --group=unit \
                --openssl \
                --libdir=/usr/lib/$DEB_HOST_MULTIARCH" &&
    CONFIGURE_ARGS="$CONFIGURE_ARGS_MODULES \
                --njs" &&
    make -j $NCPU -C pkg/contrib .njs &&
    export PKG_CONFIG_PATH=$(pwd)/pkg/contrib/njs/build &&
    ./configure $CONFIGURE_ARGS --cc-opt="$CC_OPT" --ld-opt="$LD_OPT" --modulesdir=/usr/lib/unit/debug-modules --debug &&
    make -j $NCPU unitd &&
    install -pm755 build/sbin/unitd /usr/sbin/unitd-debug &&
    make clean &&
    ./configure $CONFIGURE_ARGS --cc-opt="$CC_OPT" --ld-opt="$LD_OPT" --modulesdir=/usr/lib/unit/modules &&
    make -j $NCPU unitd &&
    install -pm755 build/sbin/unitd /usr/sbin/unitd &&
    make clean &&
    /bin/true &&
    ./configure $CONFIGURE_ARGS_MODULES --cc-opt="$CC_OPT" --modulesdir=/usr/lib/unit/debug-modules --debug &&
    ./configure python --config=/usr/local/bin/python3-config &&
    make -j $NCPU python3-install &&
    make clean &&
    ./configure $CONFIGURE_ARGS_MODULES --cc-opt="$CC_OPT" --modulesdir=/usr/lib/unit/modules &&
    ./configure python --config=/usr/local/bin/python3-config &&
    make -j $NCPU python3-install &&
    cd &&
    rm -rf /usr/src/unit &&
    for f in /usr/sbin/unitd /usr/lib/unit/modules/*.unit.so; do
        ldd $f | awk '/=>/{print $(NF-1)}' | while read n; do dpkg-query -S $n; done | sed 's/^\([^:]\+\):.*$/\1/' | sort | uniq >>/requirements.apt
    done &&
    apt-mark showmanual | xargs apt-mark auto >/dev/null &&
    { [ -z "$savedAptMark" ] || apt-mark manual $savedAptMark; } &&
    /bin/true &&
    mkdir -p /var/lib/unit/ &&
    mkdir -p /docker-entrypoint.d/ &&
    groupadd --gid 999 unit &&
    useradd \
        --uid 999 \
        --gid unit \
        --no-create-home \
        --home /nonexistent \
        --comment "unit user" \
        --shell /bin/false \
        unit &&
    apt-get update &&
    apt-get --no-install-recommends --no-install-suggests -y install curl $(cat /requirements.apt) &&
    apt-get purge -y --auto-remove build-essential &&
    rm -rf /var/lib/apt/lists/* &&
    rm -f /requirements.apt &&
    ln -sf /dev/stderr /var/log/unit.log
